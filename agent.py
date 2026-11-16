import os
import sys
import time

from db_store import save_approval_request, set_vendor_message
from dotenv import load_dotenv
from google import genai
from google.genai import types

from agent_tools import (
    check_dataset_rules,
    check_department_budget,
    check_invoice_math,
    check_vendor_matches_po,
    get_dataset_result,
    log_step,
    lookup_po,
    read_invoice,
    send_to_human_review,
    start_run,
)

from agent_tools import (
    check_dataset_rules,
    check_department_budget,          # ← add
    check_invoice_math,
    check_vendor_matches_po,
    get_dataset_result,
    log_step,
    lookup_po,
    read_invoice,
    send_to_human_review,
    start_run,
)

from db_store import save_approval_request
from rules import INFO_ONLY_CODES


# ==================================================
# 1. CONFIGURATION
# ==================================================

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
client = (
    genai.Client(
        api_key=API_KEY,
        http_options={"timeout": 45000},
    )
    if API_KEY
    else None
)


def _read_model_list():
    """Read primary and fallback model names from .env, preserving order."""
    primary = os.getenv("MODEL", "gemini-3.5-flash-lite").strip()
    fallback_models = os.getenv("FALLBACK_MODELS", "").split(",")
    legacy_fallback = os.getenv("FALLBACK_MODEL", "").strip()

    models = []
    for name in [primary, *fallback_models, legacy_fallback]:
        name = name.strip()
        if name and name not in models:
            models.append(name)

    return models or ["gemini-3.5-flash-lite"]


MODELS = _read_model_list()

try:
    MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "2"))
except (TypeError, ValueError):
    MAX_ATTEMPTS = 2

if MAX_ATTEMPTS < 1:
    raise ValueError("MAX_ATTEMPTS must be at least 1")

WAIT_SECONDS = [3, 8, 15, 30]


# ==================================================
# 2. LOGGING SAFETY
# ==================================================

def _safe_log(step, detail):
    """Never let an audit-log failure stop invoice processing."""
    try:
        log_step(step, detail)
    except Exception as exc:
        print(
            "[warning] could not record agent event '",
            step,
            "': ",
            str(exc)[:160],
            sep="",
        )


# ==================================================
# 3. SYSTEM PROMPT
# ==================================================

SYSTEM_PROMPT = """You are an accounts payable agent for a university. You check one vendor invoice at a time.

Work through these steps in order:
1. Call read_invoice to get the invoice data.
2. Call check_invoice_math to check its arithmetic.
3. If the invoice has a PO number, call lookup_po with the current file_name and the PO exactly as printed.
4. If lookup_po finds the PO exactly, call check_vendor_matches_po with the current file_name and the PO number.
5. Always call check_dataset_rules exactly once.
6. Treat the recommendation and findings from check_dataset_rules as authoritative.
6a. Call check_department_budget with the exact invoice filename.

    If the invoice total exceeds the remaining budget of the
    department that owns the matching purchase order, note this
    finding. Do not invent a budget or a department.
7. If the dataset recommendation is NEEDS_HUMAN_REVIEW, report all returned reason codes.
8. Do not approve, reject, pay, or route the invoice yourself. The Python program applies the final human-review routing after the checks are complete.
9. If the only finding is PRICE_VARIANCE_WITHIN_TOLERANCE, do not describe it as a blocking issue.

Rules:
- Never invent or correct a PO number, vendor or amount.
- Never replace the deterministic dataset recommendation with your own judgement.
- You cannot approve or pay anything. A human always makes the final approval decision.
- Call each tool at most once, unless it returned an error.
- Always call check_department_budget once, even if the PO was not found.
- Finish with a short summary. The final program will determine the recommendation from the dataset rules.
"""


def _ensure_required_tool_checks(file_name):
    """Complete mandatory deterministic checks if Gemini skipped any tool."""
    results = {}
    skipped = []
    failures = {}

    # Repeated calls are safe: most tools cache their per-invoice result.
    # This guard ensures a short Gemini response cannot bypass AP controls.
    try:
        invoice_result = read_invoice(file_name)
        results["read_invoice"] = invoice_result
    except Exception as exc:
        invoice_result = {"error": str(exc)[:180]}
        failures["read_invoice"] = str(exc)[:180]

    try:
        results["check_invoice_math"] = check_invoice_math(file_name)
    except Exception as exc:
        results["check_invoice_math"] = {
            "math_ok": False,
            "issues": [],
            "error": str(exc)[:180],
        }
        failures["check_invoice_math"] = str(exc)[:180]

    invoice_data = invoice_result if isinstance(invoice_result, dict) else {}
    po_number = (
        invoice_data.get("po_number")
        or invoice_data.get("po_reference")
        or invoice_data.get("purchase_order")
        or invoice_data.get("purchase_order_reference")
        or invoice_data.get("reference_po")
        or invoice_data.get("purchase_reference")
        or invoice_data.get("po_no")
    )

    if not po_number:
        reference_details = invoice_data.get("reference_details")
        if isinstance(reference_details, dict):
            reference_type = str(reference_details.get("reference_type") or "").lower()
            if "purchase order" in reference_type or reference_type == "po":
                po_number = reference_details.get("customer_order")

    if po_number is not None and str(po_number).strip():
        po_number = str(po_number).strip().upper()
        try:
            po_result = lookup_po(file_name, po_number)
            results["lookup_po"] = po_result
        except Exception as exc:
            po_result = {"status": "error", "note": str(exc)[:180]}
            failures["lookup_po"] = str(exc)[:180]

        if isinstance(po_result, dict) and po_result.get("po") is not None:
            try:
                results["check_vendor_matches_po"] = check_vendor_matches_po(
                    file_name,
                    po_number,
                )
            except Exception as exc:
                results["check_vendor_matches_po"] = {
                    "status": "cannot_check",
                    "note": str(exc)[:180],
                }
                failures["check_vendor_matches_po"] = str(exc)[:180]
        else:
            skipped.append(
                "check_vendor_matches_po: PO was not found exactly; manual confirmation is required."
            )
    else:
        skipped.append(
            "lookup_po and check_vendor_matches_po: no PO number was extracted."
        )

    try:
        results["check_dataset_rules"] = check_dataset_rules(file_name)
    except Exception as exc:
        results["check_dataset_rules"] = {
            "recommendation": "NEEDS_HUMAN_REVIEW",
            "findings": ["INCOMPLETE_EXTRACTION"],
            "error": str(exc)[:180],
        }
        failures["check_dataset_rules"] = str(exc)[:180]

    # Always run the department-budget check from Python as a safety net,
    # even if Gemini did not call the tool. The tool is cached per invoice,
    # so this does not duplicate a successful Gemini tool call.
    try:
        results["check_department_budget"] = check_department_budget(file_name)
    except Exception as exc:
        budget_failure = {
            "budget_ok": None,
            "note": "Budget check failed and could not be verified: " + str(exc)[:180],
        }
        results["check_department_budget"] = budget_failure
        failures["check_department_budget"] = str(exc)[:180]
        _safe_log(
            "tool:check_department_budget",
            {"file": file_name, "result": budget_failure},
        )

    _safe_log(
        "agent:required_checks_completed",
        {
            "file": file_name,
            "checks": list(results.keys()),
            "skipped": skipped,
            "failures": failures,
            "note": "Python safety guard completed required checks after Gemini returned.",
        },
    )
    return results


# ==================================================
# 4. RECORD FINAL OUTCOME
# ==================================================

def record_outcome(file_name, summary, force_human_review_reason=None):
    """Save a fail-safe recommendation based on deterministic dataset rules."""
    # Gemini may return a text response after calling only one tool. Complete
    # every required validation before creating the approval recommendation.
    _ensure_required_tool_checks(file_name)

    try:
        dataset_result = get_dataset_result(file_name)
    except Exception as exc:
        dataset_result = None
        _safe_log(
            "agent:dataset_result_read_error",
            {"file": file_name, "error": str(exc)[:200]},
        )

    # If Gemini did not call the rules tool, run the deterministic rules here.
    if not isinstance(dataset_result, dict):
        try:
            dataset_result = check_dataset_rules(file_name)
        except Exception as exc:
            dataset_result = None
            _safe_log(
                "agent:dataset_rules_error",
                {"file": file_name, "error": str(exc)[:200]},
            )

    if not isinstance(dataset_result, dict):
        dataset_result = {}

    recommendation = dataset_result.get("recommendation")
    raw_findings = dataset_result.get("findings", [])

    # Invalid rule output must fail closed to human review.
    if not isinstance(raw_findings, list):
        raw_findings = []
        recommendation = "NEEDS_HUMAN_REVIEW"

    reason_codes = list(dict.fromkeys(
        str(code).strip()
        for code in raw_findings
        if code is not None and str(code).strip()
    ))

    if recommendation not in ("READY_FOR_APPROVAL", "NEEDS_HUMAN_REVIEW"):
        recommendation = "NEEDS_HUMAN_REVIEW"
        if "INCOMPLETE_EXTRACTION" not in reason_codes:
            reason_codes.append("INCOMPLETE_EXTRACTION")

    # Unknown or blocking findings cannot accompany READY_FOR_APPROVAL.
    if any(code not in INFO_ONLY_CODES for code in reason_codes):
        recommendation = "NEEDS_HUMAN_REVIEW"

    if recommendation == "NEEDS_HUMAN_REVIEW" and not reason_codes:
        reason_codes = ["INCOMPLETE_EXTRACTION"]

    extra_note = None
    if force_human_review_reason:
        recommendation = "NEEDS_HUMAN_REVIEW"
        extra_note = str(force_human_review_reason)
        if not reason_codes:
            reason_codes = ["INCOMPLETE_EXTRACTION"]

    # Preserve machine-readable reason codes for reason_labels.py.
    reason_parts = list(reason_codes)
    if extra_note:
        reason_parts.append(extra_note)
    review_reason_text = " | ".join(reason_parts) if reason_parts else None

    if recommendation == "NEEDS_HUMAN_REVIEW":
        try:
            send_to_human_review(
                file_name,
                review_reason_text or "Manual review required.",
            )
        except Exception as exc:
            _safe_log(
                "agent:human_review_routing_error",
                {"file": file_name, "error": str(exc)[:200]},
            )

    _safe_log(
        "agent:dataset_decision",
        {
            "file": file_name,
            "recommendation": recommendation,
            "findings": reason_codes,
        },
    )

    # Save outside the Gemini retry loop. A database failure must never
    # restart Gemini or repeat completed invoice checks.
    try:
        request_id = save_approval_request(
            file_name,
            recommendation,
            summary,
            review_reason_text,
        )
    except Exception as exc:
        request_id = None
        _safe_log(
            "agent:approval_save_error",
            {"file": file_name, "error": str(exc)[:200]},
        )

    # If a human review was triggered, write a vendor-facing message so
    # the vendor sees the discrepancy on their next login.
    if request_id is not None and recommendation == "NEEDS_HUMAN_REVIEW":
        try:
            vendor_message = _build_vendor_message(reason_codes)
            if vendor_message:
                set_vendor_message(file_name, vendor_message)
        except Exception as exc:
            _safe_log(
                "agent:vendor_message_error",
                {"file": file_name, "error": str(exc)[:200]},
            )

    _safe_log(
        "agent:recorded",
        {
            "file": file_name,
            "recommendation": recommendation,
            "approval_request_id": request_id,
            "approval_saved": request_id is not None,
        },
    )

    return {
        "summary": summary,
        "recommendation": recommendation,
        "approval_request_id": request_id,
        "approval_saved": request_id is not None,
        "findings": reason_codes,
    }

# Vendor-facing message templates keyed by reason code.
# Only codes that a vendor can meaningfully act on are included.
_VENDOR_MESSAGE_TEMPLATES = {
    "MISSING_PO_REFERENCE":
        "Your invoice does not show a purchase order number. "
        "Please re-upload it with the PO number clearly printed.",

    "PO_REFERENCE_UNMAPPED":
        "The purchase order reference on your invoice does not match "
        "any PO on record. Please confirm the PO number and re-upload.",

    "VENDOR_PO_MISMATCH":
        "The vendor name or GSTIN on your invoice does not match the "
        "vendor assigned to the purchase order. Please re-upload a "
        "corrected invoice, or contact the procurement office.",

    "VENDOR_GSTIN_MISMATCH":
        "The GSTIN on your invoice does not match the vendor on record. "
        "Please re-upload a corrected invoice.",

    "INVOICE_ARITHMETIC_MISMATCH":
        "The line totals or grand total on your invoice do not add up. "
        "Please verify the amounts and re-upload a corrected invoice.",

    "PO_UNIT_PRICE_MISMATCH":
        "The unit price on your invoice differs from the approved price "
        "on the purchase order. Please re-upload the invoice at the "
        "approved price, or contact procurement to amend the PO.",

    "GRN_QUANTITY_SHORTAGE":
        "The quantity billed on your invoice exceeds the quantity "
        "recorded as received. Please re-upload with the correct "
        "quantities, or contact the receiving department.",

    "MISSING_GOODS_RECEIPT":
        "We have no goods receipt on record for this purchase order. "
        "Please contact the receiving department before re-submitting.",

    "INCOMPLETE_EXTRACTION":
        "Some details on your invoice could not be read. Please "
        "re-upload a clearer scan or a digital copy.",

    "LOW_DOCUMENT_QUALITY":
        "The scan quality of your invoice is too low to verify. "
        "Please re-upload a clearer scan or a digital copy.",
}


def _build_vendor_message(reason_codes):
    """Return a vendor-friendly explanation for the given findings."""
    if not reason_codes:
        return None

    # Take the first template whose code appears in the findings.
    # Order matters: earlier codes are more actionable than later ones.
    for code in reason_codes:
        if code in _VENDOR_MESSAGE_TEMPLATES:
            return _VENDOR_MESSAGE_TEMPLATES[code]

    # Fallback for codes we don't have a template for.
    return (
        "Your invoice was flagged for human review. "
        "Please check the details and re-upload if anything is incorrect."
    )

# ==================================================
# 5. MAIN AGENT
# ==================================================

def run_agent(file_name):
    """Run Gemini tools, then persist the deterministic recommendation once."""
    try:
        start_run(file_name)
    except Exception as exc:
        _safe_log(
            "agent:start_run_error",
            {"file": file_name, "error": str(exc)[:200]},
        )

    _safe_log("agent:start", {"file": file_name, "models": MODELS})

    if client is None:
        _safe_log(
            "agent:error",
            {"error": "GEMINI_API_KEY is missing from the .env file."},
        )
        return record_outcome(
            file_name,
            "The AI service could not start. The invoice requires human review.",
            force_human_review_reason=(
                "The AI service could not start because GEMINI_API_KEY is missing."
            ),
        )

    try:
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0,
            tools=[
                read_invoice,
                check_invoice_math,
                lookup_po,
                check_vendor_matches_po,
                check_department_budget,          # ← add
                check_dataset_rules,
                send_to_human_review,
            ],
        )
    except Exception as exc:
        _safe_log(
            "agent:configuration_error",
            {"file": file_name, "error": str(exc)[:200]},
        )
        return record_outcome(
            file_name,
            "The AI verification configuration failed. Human review is required.",
            force_human_review_reason=(
                "The AI tool configuration could not be initialized."
            ),
        )

    summary = None
    ai_failure_reason = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        model = MODELS[(attempt - 1) % len(MODELS)]

        try:
            _safe_log(
                "agent:model_attempt",
                {"attempt": attempt, "model": model},
            )

            chat = client.chats.create(model=model, config=config)
            response = chat.send_message(
                "Check the invoice file " + str(file_name) + "."
            )

            response_text = getattr(response, "text", None)
            summary = response_text or (
                "The automated checks completed without an AI text summary. "
                "The final recommendation is based on deterministic dataset rules."
            )
            _safe_log("agent:finish", {"model": model, "summary": summary})
            ai_failure_reason = None
            break

        except Exception as exc:
            error_text = str(exc)[:200]
            ai_failure_reason = error_text
            _safe_log(
                "agent:error",
                {
                    "attempt": attempt,
                    "model": model,
                    "error": error_text,
                },
            )

            # If deterministic rules already completed, don't start a fresh
            # chat and replay tools. Cached tool results in agent_tools.py
            # also protect any earlier successful tool calls.
            try:
                existing_result = get_dataset_result(file_name)
            except Exception:
                existing_result = None

            if isinstance(existing_result, dict):
                summary = (
                    "The deterministic invoice checks completed, but the AI "
                    "response failed before a final summary was returned. "
                    "The recommendation below is based on the saved dataset checks."
                )
                _safe_log(
                    "agent:retry_suppressed",
                    {
                        "file": file_name,
                        "reason": "dataset_result_already_available",
                        "attempt": attempt,
                    },
                )
                break

            if attempt < MAX_ATTEMPTS:
                wait = WAIT_SECONDS[
                    min(attempt - 1, len(WAIT_SECONDS) - 1)
                ]
                _safe_log(
                    "agent:retry",
                    {"waiting_seconds": wait, "next_model": MODELS[attempt % len(MODELS)]},
                )
                time.sleep(wait)

    if summary is None:
        _safe_log(
            "agent:gave_up",
            {"file": file_name, "models_tried": MODELS},
        )
        summary = (
            "The automated AI summary could not be completed. "
            "The invoice was routed for human review."
        )
        return record_outcome(
            file_name,
            summary,
            force_human_review_reason=(
                "The AI service was unavailable after all configured attempts. "
                + (ai_failure_reason or "No additional error details were returned.")
            ),
        )

    # Approval persistence errors are handled here, never retried through Gemini.
    return record_outcome(file_name, summary)


# ==================================================
# 6. DIRECT EXECUTION
# ==================================================

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "invoice3.pdf"
    print("=== Agent checking " + name + " ===")
    result = run_agent(name)

    print("\n" + (result["summary"] or "The automated check could not finish."))
    print("\nRecommendation: " + result["recommendation"])

    if result.get("approval_request_id") is not None:
        print(
            "Saved as approval request #"
            + str(result["approval_request_id"])
            + ". A human must approve or reject it."
        )
    elif result.get("approval_saved") is False:
        print("Approval request was not saved. Administrator recovery is required.")

    if result.get("findings"):
        print("Reason codes: " + ", ".join(result["findings"]))
