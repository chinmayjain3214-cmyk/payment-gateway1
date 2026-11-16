import csv
import hashlib
import io
import json
import time
from pathlib import Path

import streamlit as st

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    # The project's packages live in .venv. This happens when the app is
    # started with a different Python (e.g. plain `streamlit run app.py`).
    st.error(
        "This app was started with a Python that does not have the project's "
        "packages installed. Close this window and start the app by "
        "double-clicking run_app.bat (or reset_and_start_demo.bat), which "
        "uses the project's .venv. From a terminal: "
        r".venv\Scripts\python.exe -m streamlit run app.py"
    )
    st.stop()

# Load .env on every run so settings added after the app started
# (database password, API key) are picked up without a restart.
load_dotenv(Path(__file__).resolve().parent / ".env")

from po_pages import render_po_page
from grn_pages import render_grn_page
from finance_pages import render_finance_page
from approval_evidence import render_approval_evidence
from approval_workflow import (
    ROLE_LABELS,
    decide_approval_stage,
    get_approval_workflow,
    role_can_act,
)
from agent import run_agent
from auth import authenticate
from db_reports import latest_log_id, log_since, recent_log

from db_store import (
    _auto_create_payment_schedule,
    acknowledge_vendor_message,
    can_pay_through_gateway,
    cancel_payment,
    decide_request,
    get_payment_schedule,
    has_queued_approval_request,
    list_approval_requests,
    list_payment_schedules,
    list_vendor_submissions,
    log_gateway_failure,
    mark_payment_paid,
    record_gateway_payment,
    save_approval_request,
    save_log,
)
import payment_gateway as pgw


from extract_invoice import SUPPORTED_TYPES
from theme import inject_theme, LOGIN_HERO_HTML, LOGIN_FOOTER_HTML
from reason_labels import render_reasons, short_reasons
from record_store import (
    RecordStoreError,
    normalize_po_id,
    save_invoice,
)

INVOICE_DIR = Path(__file__).parent / "invoices"
EXTRACTED_DIR = Path(__file__).parent / "data" / "invoices"

ROLE_PAGES = {
    "vendor": ["Upload invoice"],
    "procurement_officer": ["Purchase Orders", "Goods Receipts"],
    "department_head": ["Approvals"],
    "finance_officer": ["Approvals"],
    "final_approver": ["Approvals"],
    "approver": ["Approvals"],  # Existing accounts continue as final approvers.
    "admin": ["Approvals", "Finance workspace", "Audit log"],
}

st.set_page_config(
    page_title="Invoice agent",
    page_icon="🧾",
    layout="wide",
)

inject_theme()


# ==================================================
# GENERAL HELPERS
# ==================================================

def require_role(user, allowed):
    if user["role"] not in allowed:
        save_log(
            "auth:access_denied",
            {"user": user["username"], "role": user["role"]},
        )
        st.error("Your role is not allowed to open this page.")
        st.stop()


def safe_name(original, content):
    """Generate a stable filename based on uploaded file contents."""
    extension = Path(original).suffix.lower()
    if extension not in SUPPORTED_TYPES:
        raise ValueError("Unsupported invoice file extension.")
    digest = hashlib.sha256(content).hexdigest()
    return "upload_" + digest + extension


def find_existing_upload(content):
    """Detect an identical document already stored in invoices/."""
    target_hash = hashlib.sha256(content).digest()
    target_size = len(content)

    try:
        if not INVOICE_DIR.is_dir():
            return None

        for path in INVOICE_DIR.glob("upload_*"):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_TYPES:
                continue
            try:
                if path.stat().st_size != target_size:
                    continue
                existing_hash = hashlib.sha256(path.read_bytes()).digest()
                if existing_hash == target_hash:
                    return path.name
            except OSError:
                continue
    except OSError:
        return None

    return None


def get_existing_approval(file_name):
    """Return the newest approval request for an uploaded file."""
    requests = list_approval_requests()
    matching = [row for row in requests if row.get("file_name") == file_name]
    if not matching:
        return None
    return max(matching, key=lambda row: row.get("id", 0))


def money(value):
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "-" if value is None else str(value)


def load_extracted(file_name):
    path = EXTRACTED_DIR / (file_name + ".json")
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None

    if isinstance(data, dict) and "_cache_version" in data and "data" in data:
        data = data["data"]
    if isinstance(data, list):
        data = data[0] if data else None
    return data if isinstance(data, dict) else None


def show_invoice(file_name):
    data = load_extracted(file_name)
    if data is None:
        st.caption("No saved reading of this invoice.")
        return

    lines = [
        "**Vendor:** " + str(data.get("vendor") or "-"),
        "**Invoice number:** " + str(data.get("invoice_number") or "-"),
        "**Date:** " + str(data.get("date") or "-"),
        "**PO number:** " + str(data.get("po_number") or "-"),
    ]
    if data.get("tax") is not None:
        lines.append("**Tax:** " + money(data.get("tax")))
    lines.append("**Total:** " + money(data.get("total")))
    st.markdown("  \n".join(lines))

    items = data.get("items") or []
    if items:
        st.dataframe(
            [
                {
                    "item": item.get("name"),
                    "qty": item.get("quantity"),
                    "unit price": money(item.get("unit_price")),
                    "line total": money(item.get("line_total")),
                }
                for item in items
            ],
            use_container_width=True,
            hide_index=True,
        )


def show_original(file_name, key):
    path = INVOICE_DIR / file_name
    if not path.exists():
        st.caption("Original invoice file is unavailable.")
        return

    if path.suffix.lower() in (".jpg", ".jpeg", ".png"):
        st.image(str(path), caption="Original invoice")

    st.download_button(
        "Download original file",
        data=path.read_bytes(),
        file_name=path.name,
        key="download_" + str(key),
    )


def event_detail(event):
    detail = event.get("detail", {})
    return detail if isinstance(detail, dict) else {}


def event_result(event):
    result = event_detail(event).get("result", {})
    return result if isinstance(result, dict) else {}


def first_event(steps, step_name):
    for event in steps:
        if event.get("step") == step_name:
            return event
    return None


def persist_invoice_business_record(file_name, steps, result):
    """Save extracted invoice data as data/invoices/inv_<po_id>.json.

    A canonical record is written only when the agent has an exact PO match.
    The original uploaded PDF/image remains in invoices/ under its hash name.
    """
    po_event = first_event(steps, "tool:lookup_po")
    if not po_event:
        return None, "No PO lookup evidence was recorded; structured invoice data was not saved."

    po_result = event_result(po_event)
    if po_result.get("status") != "found":
        return None, "A PO was not confirmed exactly; structured invoice data was not saved."

    po_record = po_result.get("po")
    if not isinstance(po_record, dict):
        return None, "The matched PO details were unavailable; structured invoice data was not saved."

    extracted = load_extracted(file_name)
    if not isinstance(extracted, dict):
        return None, "Invoice extraction data was unavailable; structured invoice data was not saved."

    po_number = str(
        po_record.get("po_number")
        or extracted.get("po_number")
        or extracted.get("po_reference")
        or ""
    ).strip()
    po_id_value = po_record.get("po_id")
    if po_id_value is None:
        po_id_value = po_record.get("id")
    if po_id_value is None:
        po_id_value = po_number

    invoice_number = str(extracted.get("invoice_number") or "").strip()
    if not invoice_number:
        return None, "The invoice number was not extracted; structured invoice data was not saved."

    try:
        po_id = normalize_po_id(po_id_value)
    except (TypeError, ValueError) as exc:
        return None, "The matched PO has no usable numeric PO ID: " + str(exc)

    def first_value(*values):
        for value in values:
            if value is not None and value != "":
                return value
        return None

    def as_number(value):
        try:
            return float(value) if value is not None and value != "" else None
        except (TypeError, ValueError):
            return None

    normalized_items = []
    raw_items = extracted.get("items") or []
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            description = first_value(item.get("description"), item.get("name"), item.get("item"))
            normalized_items.append({
                "sku": item.get("sku"),
                "name": description,
                "description": description,
                "quantity": as_number(first_value(item.get("quantity"), item.get("qty"))),
                "unit_price": as_number(first_value(item.get("unit_price"), item.get("rate"))),
                "line_total": as_number(first_value(item.get("line_total"), item.get("amount"))),
            })

    total_amount = as_number(first_value(
        extracted.get("total"),
        extracted.get("grand_total"),
        extracted.get("invoice_total"),
        extracted.get("amount_due"),
    ))
    record = {
        "vendor_id": po_record.get("vendor_id") or extracted.get("vendor_id"),
        "vendor": first_value(extracted.get("vendor"), extracted.get("vendor_name")),
        "po_id": po_id,
        "po_number": po_number,
        "invoice_number": invoice_number,
        "invoice_date": first_value(extracted.get("invoice_date"), extracted.get("date")),
        "currency": extracted.get("currency") or "INR",
        "total_amount": total_amount,
        "status": result.get("recommendation") or "PENDING",
        "items": normalized_items,
        "line_items": normalized_items,
        "source_file": file_name,
    }

    saved_path = save_invoice(po_id, record)
    return saved_path, None


def describe_step(step, detail):
    detail = detail if isinstance(detail, dict) else {}
    result = detail.get("result")
    result = result if isinstance(result, dict) else {}

    if step == "tool:read_invoice":
        if "error" in result:
            return "Could not read the invoice."
        return (
            "Read invoice "
            + str(result.get("invoice_number") or "?")
            + " from "
            + str(result.get("vendor") or "?")
        )

    if step == "tool:check_invoice_math":
        if result.get("math_ok") is True:
            return "The invoice arithmetic is correct."
        issues = result.get("issues") or []
        issue_text = " ".join(
            str(item.get("detail", ""))
            for item in issues
            if isinstance(item, dict)
        )
        return (
            "Arithmetic check needs attention. "
            + (issue_text or str(result.get("error", "No detail recorded.")))
        )

    if step == "tool:lookup_po":
        status = result.get("status")
        po = result.get("po") or {}
        if status == "found":
            return "Found purchase order " + str(po.get("po_number") or "") + "."
        if status in ("guessed", "ambiguous"):
            return str(result.get("note", "The PO number could not be confirmed."))
        return str(result.get("note", "No matching purchase order was found."))

    if step == "tool:check_vendor_matches_po":
        status = result.get("status")
        if status == "match":
            return "The vendor matches the purchase order."
        if status == "mismatch":
            return "Vendor mismatch: " + str(result.get("note", ""))
        return "The vendor check was skipped or could not be completed."

    if step == "matcher:three_way_match":
        matching_result = str(result.get("matching_result") or "").upper()
        findings = result.get("discrepancies") or []
        if matching_result == "NO_DISCREPANCIES_FOUND" and not findings:
            return "Three-way matching found no discrepancies; human approval is still required."
        if findings:
            return "Three-way matching found " + str(len(findings)) + " discrepancy/discrepancies."
        return "Three-way matching result: " + (matching_result or "inconclusive") + "."

    if step == "tool:send_to_human_review":
        return "Sent to human review: " + str(detail.get("reason", ""))
    if step == "agent:error":
        return (
            "AI service attempt "
            + str(detail.get("attempt", "?"))
            + " failed; a retry was recorded."
        )
    if step == "agent:retry":
        return (
            "Agent scheduled a retry after "
            + str(detail.get("waiting_seconds", "?"))
            + " seconds."
        )
    if step == "agent:safety_override":
        return "Independent safety check found: " + " | ".join(
            str(problem) for problem in detail.get("problems", [])
        )
    if step == "agent:gave_up":
        return "AI service was unavailable; invoice was routed to human review."
    if step == "agent:recorded":
        return (
            "Saved recommendation "
            + str(detail.get("recommendation"))
            + " as request #"
            + str(detail.get("approval_request_id"))
            + "."
        )
    if step == "agent:finish":
        return "Gemini run completed using model " + str(detail.get("model", "unknown")) + "."
    if step == "agent:start":
        return "Agent started processing the invoice."
    return None


# ==================================================
# VERIFICATION REPORT
# ==================================================

def make_check(name, status, message, detail=""):
    return {"name": name, "status": status, "message": message, "detail": detail}


def build_verification_checks(file_name, steps, result, request_record=None):
    checks = []
    extracted = load_extracted(file_name)

    read_event = first_event(steps, "tool:read_invoice")
    if read_event:
        read_result = event_result(read_event)
        if "error" in read_result:
            checks.append(make_check(
                "Invoice extraction", "review",
                "The invoice could not be read successfully.",
                str(read_result.get("error", "")),
            ))
        else:
            vendor = read_result.get("vendor") or (extracted or {}).get("vendor") or "Not recorded"
            invoice_number = read_result.get("invoice_number") or (extracted or {}).get("invoice_number") or "Not recorded"
            checks.append(make_check(
                "Invoice extraction", "passed",
                "Invoice data was read by the extraction tool.",
                "Vendor: " + str(vendor) + " · Invoice: " + str(invoice_number),
            ))
    else:
        checks.append(make_check(
            "Invoice extraction", "not_recorded",
            "No invoice-reading event was found in the retrieved run logs.",
        ))

    math_event = first_event(steps, "tool:check_invoice_math")
    if math_event:
        math_result = event_result(math_event)
        if math_result.get("math_ok") is True:
            checks.append(make_check(
                "Invoice arithmetic", "passed",
                "The arithmetic check returned math_ok = true.",
            ))
        elif math_result.get("math_ok") is False:
            issues = math_result.get("issues") or []
            issue_text = " | ".join(
                str(item.get("detail", item)) if isinstance(item, dict) else str(item)
                for item in issues
            )
            checks.append(make_check(
                "Invoice arithmetic", "review",
                "The arithmetic check identified an issue.",
                issue_text or str(math_result.get("error", "See raw event details.")),
            ))
        else:
            checks.append(make_check(
                "Invoice arithmetic", "not_recorded",
                "The arithmetic tool ran, but returned no clear math_ok value.",
                str(math_result.get("error", "")),
            ))
    else:
        checks.append(make_check(
            "Invoice arithmetic", "not_recorded",
            "No arithmetic-check event was found in the retrieved run logs.",
        ))

    po_event = first_event(steps, "tool:lookup_po")
    po_number = (extracted or {}).get("po_number") if extracted else None
    if po_event:
        po_result = event_result(po_event)
        po_status = po_result.get("status")
        po = po_result.get("po") or {}
        if po_status == "found":
            checks.append(make_check(
                "Purchase order lookup", "passed",
                "A matching purchase order was found.",
                "PO: " + str(po.get("po_number") or po_number or "Not recorded"),
            ))
        elif po_status in ("guessed", "ambiguous"):
            checks.append(make_check(
                "Purchase order lookup", "review",
                "The purchase order match was not definitive.",
                str(po_result.get("note", "Manual confirmation is required.")),
            ))
        else:
            checks.append(make_check(
                "Purchase order lookup", "review",
                "The purchase order could not be confirmed.",
                str(po_result.get("note", "No matching purchase order was found.")),
            ))
    elif extracted is not None and not po_number:
        checks.append(make_check(
            "Purchase order lookup", "review",
            "No PO number was present in the extracted invoice data.",
            "The PO comparison could not be performed from the extracted PO number.",
        ))
    elif po_number:
        checks.append(make_check(
            "Purchase order lookup", "not_recorded",
            "A PO number was extracted, but no lookup event was found.",
            "Extracted PO: " + str(po_number),
        ))
    else:
        checks.append(make_check(
            "Purchase order lookup", "not_recorded",
            "There is not enough recorded data to determine whether PO lookup was performed.",
        ))

    vendor_event = first_event(steps, "tool:check_vendor_matches_po")
    if vendor_event:
        vendor_result = event_result(vendor_event)
        vendor_status = vendor_result.get("status")
        if vendor_status == "match":
            checks.append(make_check(
                "Vendor verification", "passed",
                "The vendor matches the purchase order.",
            ))
        elif vendor_status == "mismatch":
            checks.append(make_check(
                "Vendor verification", "review",
                "The vendor does not match the purchase order.",
                str(vendor_result.get("note", "")),
            ))
        else:
            checks.append(make_check(
                "Vendor verification", "not_recorded",
                "The vendor verification tool did not return a definitive match status.",
                str(vendor_result.get("note", "")),
            ))
    elif po_event and event_result(po_event).get("status") not in ("found", "guessed"):
        checks.append(make_check(
            "Vendor verification", "not_run",
            "Vendor matching was not run because a usable PO was not found.",
        ))
    else:
        checks.append(make_check(
            "Vendor verification", "not_recorded",
            "No vendor-to-PO verification event was found.",
        ))

    # Three-way matching is a separate deterministic backend result.
    matching_event = first_event(steps, "matcher:three_way_match")
    if matching_event:
        matching_result = event_result(matching_event)
        matching_outcome = str(matching_result.get("matching_result") or "").upper()
        matching_findings = matching_result.get("discrepancies") or []
        if matching_outcome == "NO_DISCREPANCIES_FOUND" and not matching_findings:
            checks.append(make_check(
                "Three-way matching", "passed",
                "No PO / GRN / invoice discrepancies were found. Human approval is still required.",
            ))
        elif matching_findings or matching_outcome == "DISCREPANCIES_FOUND":
            finding_text = " | ".join(
                str(item.get("type", "ISSUE")) + ": " + str(item.get("details", ""))
                for item in matching_findings[:5]
                if isinstance(item, dict)
            )
            checks.append(make_check(
                "Three-way matching", "review",
                "The matcher found discrepancies that require human review.",
                finding_text or "The matcher flagged this invoice for human review.",
            ))
        else:
            checks.append(make_check(
                "Three-way matching", "not_recorded",
                "The matcher ran but did not return a recognised result.",
                str(matching_result.get("recommendation") or ""),
            ))
    else:
        checks.append(make_check(
            "Three-way matching", "not_recorded",
            "No three-way matching event was recorded for this invoice.",
        ))

    recommendation = result.get("recommendation")
    recorded_reason = str(request_record.get("review_reason") or "") if isinstance(request_record, dict) else ""
    if recommendation == "READY_FOR_APPROVAL":
        checks.append(make_check(
            "Independent Python safety check", "passed",
            "The final programmatic checks produced no blocking review reason.",
        ))
    elif recommendation == "NEEDS_HUMAN_REVIEW":
        checks.append(make_check(
            "Independent Python safety check", "review",
            "The final programmatic decision requires human review.",
            recorded_reason or "The recommendation was NEEDS_HUMAN_REVIEW.",
        ))
    else:
        checks.append(make_check(
            "Independent Python safety check", "not_recorded",
            "No final recommendation was available to display.",
        ))

    return checks


def render_check_card(check):
    with st.container(border=True):
        left, right = st.columns([3, 1])
        with left:
            st.markdown("**" + check["name"] + "**")
            st.write(check["message"])
            if check.get("detail"):
                st.caption(check["detail"])
        with right:
            status = check["status"]
            if status == "passed":
                st.success("Passed")
            elif status == "review":
                st.warning("Review")
            elif status == "not_run":
                st.info("Not run")
            else:
                st.caption("Not recorded")


def render_verification_report(file_name, result, steps, request_record=None):
    recommendation = result.get("recommendation")
    checks = build_verification_checks(file_name, steps, result, request_record)
    passed_count = sum(1 for check in checks if check["status"] == "passed")
    review_count = sum(1 for check in checks if check["status"] == "review")
    unrecorded_count = sum(1 for check in checks if check["status"] in ("not_recorded", "not_run"))

    finish_event = first_event(steps, "agent:finish")
    model_name = event_detail(finish_event).get("model") if finish_event else None

    st.divider()
    st.markdown("<div class='page-eyebrow'>EVIDENCE-BASED VERIFICATION</div>", unsafe_allow_html=True)
    st.title("AI verification report")

    top_left, top_right = st.columns([3, 1])
    with top_left:
        if recommendation == "READY_FOR_APPROVAL":
            st.success("AI recommendation: Ready for human approval. This is not an approval or payment decision.")
        elif recommendation == "NEEDS_HUMAN_REVIEW":
            st.warning("AI recommendation: Human review required. Do not treat this invoice as cleared.")
        else:
            st.info("A final recommendation was not recorded.")
        if result.get("summary"):
            st.markdown("**Agent summary**")
            st.write(result["summary"])

    with top_right:
        st.markdown("**Run information**")
        st.caption("Invoice: " + file_name)
        if result.get("approval_saved"):
            st.success("Approval request saved to PostgreSQL. Request ID: " + str(result.get("approval_request_id")))
        elif result.get("recovery_queued"):
            st.warning("Approval request saved locally. It will synchronize when PostgreSQL becomes available.")
        else:
            st.error("Approval request could not be saved. Administrator recovery is required.")
        if model_name:
            st.caption("Gemini model: " + str(model_name))

    metric1, metric2, metric3 = st.columns(3)
    metric1.metric("Checks passed", passed_count)
    metric2.metric("Need review", review_count)
    metric3.metric("Not recorded / run", unrecorded_count)

    st.markdown("### Verification breakdown")
    for start in range(0, len(checks), 2):
        col1, col2 = st.columns(2, gap="medium")
        with col1:
            render_check_card(checks[start])
        if start + 1 < len(checks):
            with col2:
                render_check_card(checks[start + 1])

    st.markdown("### Invoice evidence")
    invoice_tab, original_tab = st.tabs(["Extracted invoice data", "Original document"])
    with invoice_tab:
        show_invoice(file_name)
    with original_tab:
        show_original(file_name, str(result.get("approval_request_id") or "report"))

    st.markdown("### Agent execution trace")
    if not steps:
        st.info("No run events were returned by the audit log query.")
    else:
        for event in steps:
            description = describe_step(event.get("step", ""), event.get("detail", {}))
            if description:
                st.write("• " + description)

    with st.expander("Inspect raw run events"):
        for event in steps:
            st.markdown("**#" + str(event.get("id", "?")) + " · " + str(event.get("step", "unknown")) + "**")
            st.json(event.get("detail", {}))


# ==================================================
# AUDIT HELPERS
# ==================================================

def audit_category(step):
    name = str(step).lower()
    if name.startswith("tool:"):
        return "AI tools"
    if name.startswith("agent:"):
        return "AI agent"
    if "approval" in name or "human" in name or "decision" in name:
        return "Human decisions"
    if "auth" in name:
        return "Access"
    if "vendor" in name:
        return "Vendor activity"
    return "System"


def create_audit_csv(rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Time", "Category", "Event", "Details"])
    for row in rows:
        writer.writerow([
            row.get("id", ""),
            str(row.get("time", "")),
            audit_category(row.get("step", "")),
            row.get("step", ""),
            json.dumps(row.get("detail", {}), ensure_ascii=False, default=str),
        ])
    return output.getvalue().encode("utf-8-sig")


# ==================================================
# LOGIN PAGE
# ==================================================

def login_screen():
    left, right = st.columns([1.2, 0.85], gap="large")
    with left:
        st.html(LOGIN_HERO_HTML)
    with right:
        st.markdown("<div class='login-label'>Account access</div>", unsafe_allow_html=True)
        st.markdown("## Welcome back")
        st.caption("Sign in to access your invoice workspace.")

        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            submitted = st.form_submit_button("Sign in →", type="primary", use_container_width=True)

        if submitted:
            try:
                user = authenticate(username, password)
            except Exception as exc:
                st.error("Could not reach the database. Check that PostgreSQL is running and that .env is correct.")
                st.caption(str(exc)[:200])
                return
            if user:
                st.session_state["user"] = user
                st.rerun()
            else:
                st.error("Wrong username or password. Passwords are case-sensitive, so check Caps Lock.")

        st.html(LOGIN_FOOTER_HTML)
        st.caption("Demo accounts are listed in the README. Passwords are case-sensitive.")


# ==================================================
# VENDOR UPLOAD PAGE
# ==================================================
                
# ==================================================
# VENDOR UPLOAD PAGE
# ==================================================

def upload_page(user):
    """Vendor workspace: upload new invoice or view previous submissions."""
    require_role(user, ["vendor"])
    st.markdown(
        "<div class='page-eyebrow'>VENDOR WORKSPACE</div>",
        unsafe_allow_html=True,
    )
    st.title("Submit an invoice")
    st.caption(
        "Upload your invoice for automated verification. "
        "Any discrepancies flagged by the agent appear in 'My submissions'."
    )

    upload_tab, submissions_tab = st.tabs(
        ["Upload invoice", "My submissions"]
    )

    with submissions_tab:
        _render_vendor_submissions(user)

    with upload_tab:
        _render_upload_form(user)


def _render_vendor_submissions(user):
    """Show this vendor's previous uploads, with discrepancy messages."""

    st.subheader("Your submissions")
    st.caption(
        "Any discrepancies flagged by the verification agent appear here. "
        "Re-upload a corrected invoice if requested."
    )

    try:
        submissions = list_vendor_submissions(user["username"])
    except Exception as exc:
        st.error("Could not load your submissions.")
        st.caption(str(exc)[:200])
        return

    if not submissions:
        st.info("You have not submitted any invoices yet.")
        return

    for row in submissions:
        request_id = row["id"]
        file_name = row["file_name"]
        status = row["status"]
        vendor_message = row.get("vendor_message")

        with st.container(border=True):
            header_left, header_right = st.columns([3, 1])

            with header_left:
                st.markdown(f"### {file_name}")
                st.caption(
                    f"Submitted: {row['created_at']} · Request #{request_id}"
                )

            with header_right:
                if status == "PENDING":
                    st.info("Awaiting review")
                elif status == "APPROVED":
                    st.success("Approved")
                elif status == "REJECTED":
                    st.error("Rejected")
                else:
                    st.caption(status or "—")

            # Vendor-facing message takes priority — it's the actionable bit.
            if vendor_message:
                st.warning(f"**Action needed:** {vendor_message}")

                if st.button(
                    "I've read this / will re-upload",
                    key=f"ack_{request_id}",
                ):
                    try:
                        if acknowledge_vendor_message(request_id):
                            st.success("Acknowledged.")
                            st.rerun()
                        else:
                            st.info("Already acknowledged.")
                    except Exception as exc:
                        st.error("Could not acknowledge.")
                        st.caption(str(exc)[:200])

            # Expandable details for the vendor.
            with st.expander("What did the agent check?"):
                if row.get("review_reason"):
                    st.write("**Findings:**")
                    render_reasons(row["review_reason"])
                else:
                    st.write("No issues recorded.")

                if row.get("summary"):
                    st.write("**Agent summary:**")
                    st.write(row["summary"])

            # Download original.
            path = INVOICE_DIR / file_name
            if path.exists():
                st.download_button(
                    "Download your original",
                    data=path.read_bytes(),
                    file_name=path.name,
                    key=f"dl_{request_id}",
                )


def _render_upload_form(user):
    """Render the upload form. Called from upload_page's 'Upload invoice' tab."""

    file_types = [extension.lstrip(".") for extension in sorted(SUPPORTED_TYPES)]
    left, right = st.columns([1.5, 0.8], gap="large")
    uploaded = None
    process_clicked = False

    with left:
        with st.container(border=True):
            st.subheader("01 · Upload your document")
            st.write("Choose the invoice file you want the AI agent to verify.")
            uploaded = st.file_uploader(
                "Select invoice",
                type=file_types,
                help="Supported formats: " + ", ".join(file_types),
            )
            if uploaded is not None:
                st.divider()
                st.markdown("**Selected file**")
                file_col, size_col = st.columns(2)
                with file_col:
                    st.write("📄 " + uploaded.name)
                with size_col:
                    st.write(f"{uploaded.size / 1024:,.1f} KB")
                process_clicked = st.button(
                    "Run AI verification →",
                    type="primary",
                    use_container_width=True,
                    key="run_invoice_agent",
                )
            else:
                st.info("Upload a PDF or image to begin the verification process.")

    with right:
        with st.container(border=True):
            st.markdown("### How it works")
            st.markdown('<div class="upload-step"><b>01 · Upload</b><br><small>Submit your invoice document.</small></div>', unsafe_allow_html=True)
            st.write("")
            st.markdown('<div class="upload-step"><b>02 · Verify</b><br><small>AI reads the invoice and checks company records.</small></div>', unsafe_allow_html=True)
            st.write("")
            st.markdown('<div class="upload-step"><b>03 · Review</b><br><small>A human makes the final approval decision.</small></div>', unsafe_allow_html=True)
            st.divider()
            st.caption("AI recommendations do not automatically approve payments.")

    if uploaded is None or not process_clicked:
        return

    uploaded_bytes = uploaded.getvalue()
    if not uploaded_bytes:
        st.error("The selected invoice is empty.")
        return

    try:
        existing_upload = find_existing_upload(uploaded_bytes)
    except Exception as exc:
        st.error("Could not check whether this invoice was previously submitted.")
        st.caption(str(exc)[:200])
        return

    if existing_upload:
        st.warning("This exact invoice document has already been uploaded. Duplicate processing was prevented.")
        st.caption("Previous upload: " + existing_upload)
        try:
            previous_request = get_existing_approval(existing_upload)
            if previous_request:
                st.info(
                    "Existing request #" + str(previous_request["id"])
                    + " · " + str(previous_request["recommendation"])
                    + " · " + str(previous_request["status"])
                )
            else:
                st.warning("The document exists, but no matching approval request was found. Please ask an administrator to inspect the earlier submission before retrying.")
        except Exception as exc:
            st.warning("The previous upload was detected, but its approval request could not be retrieved.")
            st.caption(str(exc)[:150])
        return

    try:
        file_name = safe_name(uploaded.name, uploaded_bytes)
    except ValueError as exc:
        st.error(str(exc))
        return

    file_path = INVOICE_DIR / file_name
    try:
        INVOICE_DIR.mkdir(parents=True, exist_ok=True)
        with file_path.open("xb") as file_handle:
            file_handle.write(uploaded_bytes)
    except FileExistsError:
        st.warning("This document was already saved by another submission. It will not be processed again.")
        return
    except OSError as exc:
        st.error("Could not save the uploaded invoice.")
        st.caption(str(exc)[:200])
        return

    try:
        audit_saved = save_log("vendor:upload", {"user": user["username"], "file": file_name})
        if audit_saved is False:
            st.warning("The invoice was saved, but its upload audit entry could not be saved.")
    except Exception as exc:
        st.warning("The invoice was saved, but its upload audit entry failed.")
        st.caption(str(exc)[:150])

    try:
        last_id = latest_log_id()
    except Exception:
        last_id = None
        st.warning("Audit tracing is temporarily unavailable. Invoice processing will continue.")

    try:
        with st.spinner("The AI agent is reading and checking your invoice..."):
            result = run_agent(file_name)
        if not isinstance(result, dict):
            raise RuntimeError("The agent returned an invalid result.")
    except Exception as exc:
        failure_summary = "Automated processing stopped unexpectedly. Human verification is required."
        failure_reason = "INCOMPLETE_EXTRACTION | Automated processing failed unexpectedly."
        st.error("Invoice processing encountered an unexpected error. The original document has been saved.")
        st.caption(str(exc)[:200])
        try:
            request_id = save_approval_request(file_name, "NEEDS_HUMAN_REVIEW", failure_summary, failure_reason)
            if request_id is not None:
                st.warning("Fallback human-review request saved as #" + str(request_id))
            elif has_queued_approval_request(file_name):
                st.warning("Fallback human-review request saved locally. It will synchronize when PostgreSQL becomes available.")
            else:
                st.error("The fallback review request could not be saved to PostgreSQL or local recovery storage. Administrator intervention is required.")
        except Exception as db_error:
            st.error("Database recovery also failed. The original invoice remains saved at: " + file_name)
            st.caption(str(db_error)[:150])
        return

    try:
        steps = log_since(last_id) if last_id is not None else []
    except Exception:
        steps = []
        st.warning("The invoice was processed, but its execution trace could not be retrieved.")

    structured_path = None
    try:
        structured_path, structured_note = persist_invoice_business_record(
            file_name, steps, result
        )
        if structured_path is not None:
            st.success(
                "Structured invoice record saved: "
                + str(structured_path.relative_to(Path(__file__).resolve().parent))
            )
        elif structured_note:
            st.info(structured_note)
    except RecordStoreError as exc:
        st.warning("The original invoice and approval record are safe, but the PO-based JSON record was not saved.")
        st.caption(str(exc)[:250])
    except Exception as exc:
        st.warning("The invoice was processed, but its PO-based JSON record could not be saved.")
        st.caption(str(exc)[:250])

    # Run the standalone matcher for this newly saved canonical invoice only.
    if structured_path is not None:
        try:
            from matcher import process_invoice_record

            with st.spinner("Running invoice, purchase order and goods-receipt matching..."):
                matching_report = process_invoice_record(structured_path)

            if not isinstance(matching_report, dict):
                raise RuntimeError("The matcher returned an invalid report.")

            matching_event_detail = {
                "file": file_name,
                "result": matching_report,
            }
            local_matching_event = {
                "step": "matcher:three_way_match",
                "detail": matching_event_detail,
            }

            try:
                matching_logged = save_log(
                    "matcher:three_way_match",
                    matching_event_detail,
                )
                if matching_logged is False:
                    st.warning("Matching completed, but its audit event could not be saved.")
            except Exception as log_error:
                st.warning("Matching completed, but its audit event could not be saved.")
                st.caption(str(log_error)[:150])

            matching_outcome = str(matching_report.get("matching_result") or "").upper()
            discrepancies = matching_report.get("discrepancies") or []
            if matching_outcome == "NO_DISCREPANCIES_FOUND" and not discrepancies:
                st.success("Three-way matching found no discrepancies. Human approval is still required.")
            else:
                st.warning(
                    "Three-way matching requires human review: "
                    + str(len(discrepancies)) + " finding(s)."
                )
                for finding in discrepancies:
                    if isinstance(finding, dict):
                        st.caption(
                            str(finding.get("type") or "ISSUE") + ": "
                            + str(finding.get("details") or "")
                        )

            # Refresh the run evidence so the upload report includes matching.
            try:
                if last_id is not None:
                    steps = log_since(last_id)
                else:
                    steps = recent_log(500)
                if not any(
                    row.get("step") == "matcher:three_way_match"
                    and event_detail(row).get("file") == file_name
                    for row in steps if isinstance(row, dict)
                ):
                    steps.append(local_matching_event)
            except Exception:
                steps.append(local_matching_event)

        except Exception as matching_error:
            st.warning("The invoice was saved, but three-way matching could not be completed.")
            st.caption(str(matching_error)[:200])

    request_id = result.get("approval_request_id")
    request_record = None
    if request_id is not None:
        try:
            request_record = next(
                (row for row in list_approval_requests() if str(row.get("id")) == str(request_id)),
                None,
            )
        except Exception:
            st.warning("The approval record was saved, but its details could not be retrieved.")

    render_verification_report(file_name, result, steps, request_record)


# ==================================================
# APPROVALS PAGE
# ==================================================
def _render_payment_schedule_tab(user):
    """Show payment schedules to approvers; restrict actions to finance/admin."""
    st.subheader("Upcoming payments")
    can_process = str(user.get("role", "")).strip().lower() in {
        "finance_officer", "admin"
    }
    st.caption(
        "Approved invoices appear here automatically. "
        + ("Authorised finance users can process or cancel scheduled entries."
           if can_process else "Final Approvers can pay invoices they approved through the payment gateway. "
           "Other payment actions are restricted to Finance Officers and Admins.")
    )

    try:
        scheduled = list_payment_schedules("SCHEDULED")
        history = [
            row for row in list_payment_schedules()
            if row["payment_status"] != "SCHEDULED"
        ]
    except Exception as exc:
        st.error("Could not reach the payments table.")
        st.caption(str(exc)[:200])
        return

    total_scheduled = sum(float(row["invoice_amount"] or 0) for row in scheduled)
    m1, m2, m3 = st.columns(3)
    m1.metric("Awaiting payment", len(scheduled))
    m2.metric("Total scheduled", f"{total_scheduled:,.2f}")
    m3.metric("Paid / cancelled", len(history))

    if not scheduled:
        st.info("No payments are waiting to be processed.")
    else:
        for row in scheduled:
            payment_id = row["id"]
            with st.container(border=True):
                left, right = st.columns([3, 1])
                with left:
                    st.markdown("### " + str(row["invoice_number"] or "Invoice"))
                    st.caption(
                        "Vendor: " + str(row["vendor_name"] or "—")
                        + " · Department: " + str(row["department_id"] or "—")
                        + " · Approval request #" + str(row["approval_request_id"])
                    )
                    st.write("**Amount:** " + f"{float(row['invoice_amount'] or 0):,.2f}")
                    st.write("**Scheduled for:** " + str(row["scheduled_payment_date"]))

                with right:
                    try:
                        can_gateway_pay = can_pay_through_gateway(
                            row, user.get("username"), user.get("role")
                        )
                    except Exception:
                        can_gateway_pay = False
                    if can_gateway_pay and st.button(
                        "Pay now", type="primary",
                        key="gateway_" + str(payment_id), use_container_width=True,
                    ):
                        st.session_state["payment_window"] = {"payment_id": payment_id}
                        st.rerun()

                    if not can_process:
                        if not can_gateway_pay:
                            st.caption("Finance-only actions")
                        continue
                    batch_id = st.text_input(
                        "Batch ID (optional)",
                        key="batch_" + str(payment_id),
                        placeholder="e.g. BATCH-2026-11",
                    )
                    if st.button(
                        "Mark as paid (offline)",
                        key="pay_" + str(payment_id), use_container_width=True,
                    ):
                        try:
                            result = mark_payment_paid(
                                payment_id,
                                paid_by=user["username"],
                                batch_id=batch_id or None,
                                actor_role=user.get("role"),
                            )
                            if result:
                                st.success("Marked as paid: " + str(result))
                                st.rerun()
                            else:
                                st.warning("This payment was already processed.")
                        except Exception as exc:
                            st.error("Could not update payment.")
                            st.caption(str(exc)[:200])

                    if st.button(
                        "Cancel", key="cancel_" + str(payment_id),
                        use_container_width=True,
                    ):
                        try:
                            result = cancel_payment(
                                payment_id,
                                cancelled_by=user["username"],
                                actor_role=user.get("role"),
                            )
                            if result:
                                st.info("Payment cancelled: " + str(result))
                                st.rerun()
                            else:
                                st.warning("This payment was already processed.")
                        except Exception as exc:
                            st.error("Could not cancel payment.")
                            st.caption(str(exc)[:200])

    st.divider()
    st.markdown("### Payment history")
    if not history:
        st.caption("No payments have been processed yet.")
    else:
        st.dataframe(
            [
                {
                    "Invoice": row["invoice_number"],
                    "Vendor": row["vendor_name"],
                    "Amount": f"{float(row['invoice_amount'] or 0):,.2f}",
                    "Status": row["payment_status"],
                    "Scheduled": str(row["scheduled_payment_date"]),
                    "Paid at": str(row["paid_at"] or ""),
                    "Paid by": row["paid_by"] or "",
                    "Batch": row["payment_batch_id"] or "",
                }
                for row in history
            ],
            use_container_width=True,
            hide_index=True,
        )

@st.dialog("Confirm decision", width="small")
def _confirm_decision_dialog(
    request_id,
    decision,
    file_name,
    username,
    user_role,
    note,
):
    """Modal confirmation for approve/reject actions."""

    action_verb = "approve" if decision == "APPROVED" else "reject"
    action_title = "Approve" if decision == "APPROVED" else "Reject"

    st.markdown(f"### {action_title} request #{request_id}?")

    st.write(f"**File:** `{file_name}`")

    if note:
        st.caption(f"Your note: {note}")

    if decision == "APPROVED":
        st.info(
            "Approving this stage advances the invoice to the next "
            "approval stage. If this is the final stage, the invoice "
            "is fully approved, a payment schedule is created and the "
            "payment window opens."
        )
    else:
        st.warning(
            "Rejecting ends the approval workflow for this invoice. "
            "This cannot be undone."
        )

    st.divider()
    confirm_col, cancel_col = st.columns(2)

    if confirm_col.button(
        f"Yes, {action_verb}",
        type="primary",
        use_container_width=True,
        key=f"confirm_{decision}_{request_id}",
    ):
        try:
            outcome = decide_approval_stage(
                request_id, decision, username, user_role, note
            )

            if outcome["request_status"] == "APPROVED":
                message = (
                    "Invoice fully approved after all three stages: "
                    + str(file_name)
                )
                try:
                    payment_id = _auto_create_payment_schedule(
                        approval_request_id=request_id,
                        invoice_number=file_name,
                    )
                    # Open the payment gateway window for the final approver.
                    st.session_state["payment_window"] = {"payment_id": payment_id}
                    message += ". Payment schedule #" + str(payment_id) + " created."
                except Exception as pay_exc:
                    message += (
                        " WARNING: payment schedule could not be created: "
                        + str(pay_exc)[:120]
                    )
            elif outcome["request_status"] == "REJECTED":
                message = (
                    "Invoice rejected at "
                    + str(outcome["stage"]) + ": " + str(file_name)
                )
            else:
                message = (
                    str(outcome["stage"]) + " approved. Next stage: "
                    + str(outcome["next_stage"]) + "."
                )

            if not outcome.get("audit_recorded"):
                message += (
                    " WARNING: the decision was saved, but its audit "
                    "event could not be written."
                )

            st.session_state["message"] = message

        except Exception as exc:
            st.session_state["message"] = (
                "Could not save the decision. " + str(exc)[:200]
            )

        st.session_state.pop("pending_decision", None)
        st.rerun()

    if cancel_col.button(
        "Cancel",
        use_container_width=True,
        key=f"cancel_{decision}_{request_id}",
    ):
        st.session_state.pop("pending_decision", None)
        st.rerun()

def _inr(value):
    try:
        return "₹" + f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "₹—"


def _clear_gateway_state(payment_id):
    for key in ("pgw_order_", "pgw_result_"):
        st.session_state.pop(key + str(payment_id), None)


@st.dialog("Payment gateway", width="large")
def _payment_gateway_dialog(payment_id, user):
    """Sandbox checkout window opened after an invoice is fully approved."""
    order_key = "pgw_order_" + str(payment_id)
    result_key = "pgw_result_" + str(payment_id)
    username = user.get("username")
    user_role = str(user.get("role") or "").strip().lower()

    try:
        payment = get_payment_schedule(payment_id)
    except Exception as exc:
        st.error("Could not load the payment schedule.")
        st.caption(str(exc)[:200])
        return
    if payment is None:
        st.error("Payment schedule #" + str(payment_id) + " was not found.")
        return

    st.markdown(
        "<div style='display:flex;justify-content:space-between;align-items:center;'>"
        "<div><b style='font-size:1.15rem;'>🔒 " + pgw.GATEWAY_NAME + "</b><br>"
        "<small>Merchant: University Accounts Payable</small></div>"
        "<div style='text-align:right;'><small>Amount payable</small><br>"
        "<b style='font-size:1.6rem;'>" + _inr(payment["invoice_amount"]) + "</b></div></div>",
        unsafe_allow_html=True,
    )
    st.warning(pgw.SANDBOX_NOTICE, icon="🧪")

    info1, info2, info3 = st.columns(3)
    info1.markdown("**Payee (vendor)**  \n" + str(payment["vendor_name"] or "—"))
    info2.markdown("**Invoice**  \n" + str(payment["invoice_number"] or "—"))
    info3.markdown(
        "**Department · Request**  \n"
        + str(payment["department_id"] or "—") + " · #" + str(payment["approval_request_id"])
    )
    st.divider()

    result = st.session_state.get(result_key)

    # ---------- Result screens ----------
    if result and result.get("status") == "SUCCESS":
        st.success("Payment successful", icon="✅")
        st.markdown(
            "**Transaction ID:** `" + str(result["transaction_id"]) + "`  \n"
            "**Order ID:** `" + str(result["order_id"]) + "`  \n"
            "**Amount:** " + _inr(result["amount"]) + "  \n"
            "**Paid with:** " + str(result["method_display"]) + "  \n"
            "**Processed at (UTC):** " + str(result["processed_at"]) + "  \n"
            "**Paid by:** " + str(username)
        )
        st.caption("The payment schedule is now marked PAID and the transaction is in the audit log.")
        if st.button("Done", type="primary", use_container_width=True, key="pgw_done_" + str(payment_id)):
            st.session_state["message"] = (
                "Payment of " + _inr(result["amount"]) + " completed for "
                + str(payment["invoice_number"]) + ". Transaction " + str(result["transaction_id"]) + "."
            )
            _clear_gateway_state(payment_id)
            st.rerun()
        return

    if result and result.get("status") == "FAILED":
        st.error("Payment failed: " + str(result.get("failure_reason") or "Unknown reason."), icon="❌")
        st.caption("Nothing was charged. The invoice stays in the payment schedule as SCHEDULED.")
        retry_col, close_col = st.columns(2)
        if retry_col.button("Try again", type="primary", use_container_width=True, key="pgw_retry_" + str(payment_id)):
            st.session_state.pop(result_key, None)
            st.session_state.pop(order_key, None)
            st.rerun(scope="fragment")
        if close_col.button("Close", use_container_width=True, key="pgw_close_failed_" + str(payment_id)):
            _clear_gateway_state(payment_id)
            st.rerun()
        return

    # ---------- Checkout form ----------
    if str(payment["payment_status"] or "").upper() != "SCHEDULED":
        st.info(
            "This payment is already " + str(payment["payment_status"])
            + (". Reference: " + str(payment["payment_batch_id"]) if payment.get("payment_batch_id") else ".")
        )
        return

    try:
        allowed = can_pay_through_gateway(payment, username, user_role)
    except Exception as exc:
        st.error("Could not verify payment permission.")
        st.caption(str(exc)[:200])
        return
    if not allowed:
        st.info(
            "Only the Final Approver who approved this invoice, a Finance Officer "
            "or an Admin can pay it."
        )
        return

    if order_key not in st.session_state:
        try:
            st.session_state[order_key] = pgw.create_order(payment)
        except pgw.PaymentValidationError as exc:
            st.error(str(exc))
            return
    order = st.session_state[order_key]
    st.caption("Order " + order["order_id"])

    method = st.radio(
        "Pay using",
        pgw.METHODS,
        format_func=lambda m: pgw.METHOD_LABELS[m],
        horizontal=True,
        key="pgw_method_" + str(payment_id),
    )

    details = {}
    if method == "UPI":
        details["vpa"] = st.text_input(
            "UPI ID", placeholder="name@bank", key="pgw_vpa_" + str(payment_id)
        )
    elif method == "CARD":
        details["card_number"] = st.text_input(
            "Card number", placeholder="4111 1111 1111 1111",
            max_chars=23, key="pgw_card_" + str(payment_id),
        )
        details["name_on_card"] = st.text_input(
            "Name on card", key="pgw_name_" + str(payment_id)
        )
        exp_col, cvv_col = st.columns(2)
        details["expiry"] = exp_col.text_input(
            "Expiry (MM/YY)", placeholder="12/30", max_chars=7, key="pgw_exp_" + str(payment_id)
        )
        details["cvv"] = cvv_col.text_input(
            "CVV", type="password", max_chars=4, key="pgw_cvv_" + str(payment_id)
        )
    else:
        details["bank"] = st.selectbox(
            "Choose your bank", pgw.NETBANKING_BANKS, key="pgw_bank_" + str(payment_id)
        )

    with st.expander("Sandbox test credentials"):
        st.markdown(
            "- Card **4111 1111 1111 1111**, any future expiry, any CVV → success  \n"
            "- Card **4000 0000 0000 0002** → declined  \n"
            "- UPI **success@sandbox** → success · **failure@sandbox** → declined  \n"
            "- Net banking **Sandbox Bank (decline)** → declined"
        )

    pay_col, cancel_col = st.columns([2, 1])
    if pay_col.button(
        "Pay " + _inr(order["amount"]), type="primary",
        use_container_width=True, key="pgw_pay_" + str(payment_id),
    ):
        try:
            with st.spinner("Contacting " + pgw.GATEWAY_NAME + "..."):
                time.sleep(1.2)
                outcome = pgw.charge(order, method, details)
        except pgw.PaymentValidationError as exc:
            st.error(str(exc))
            return

        if outcome["status"] == "SUCCESS":
            try:
                recorded = record_gateway_payment(
                    payment_id, outcome, username, actor_role=user_role
                )
            except Exception as exc:
                st.error("The gateway approved the charge, but it could not be recorded.")
                st.caption(str(exc)[:200])
                return
            if recorded is None:
                st.warning("This payment was already processed by someone else.")
                return
        else:
            try:
                log_gateway_failure(payment_id, outcome, username)
            except Exception:
                pass

        st.session_state[result_key] = outcome
        st.rerun(scope="fragment")

    if cancel_col.button("Pay later", use_container_width=True, key="pgw_later_" + str(payment_id)):
        _clear_gateway_state(payment_id)
        st.session_state["message"] = (
            "Payment window closed. " + str(payment["invoice_number"])
            + " stays in the Payment schedule tab until it is paid."
        )
        st.rerun()


def approvals_page(user):
    allowed_roles = ["department_head", "finance_officer", "final_approver", "approver", "admin"]
    require_role(user, allowed_roles)
    user_role = str(user.get("role") or "").strip().lower()
    role_label = ROLE_LABELS.get(user_role, user_role.replace("_", " ").title())

    st.markdown("<div class='page-eyebrow'>HUMAN REVIEW WORKSPACE</div>", unsafe_allow_html=True)
    st.title("Invoice approval center")
    st.caption("Three-stage review: Department Head → Finance Officer → Final Approver. Each stage records its own decision.")

    if "message" in st.session_state:
        st.success(st.session_state.pop("message"))
    
    # If a decision was queued in a previous interaction, open the
    # confirmation modal. This runs before the rest of the page renders.
    
    pending = st.session_state.get("pending_decision")
    if pending:
        _confirm_decision_dialog(**pending)
    elif st.session_state.get("payment_window"):
        # Pop first so closing the window with X does not reopen it.
        # Interactions inside the dialog rerun only the dialog itself.
        window = st.session_state.pop("payment_window")
        _payment_gateway_dialog(window["payment_id"], user)

    try:
        all_pending = list_approval_requests("PENDING")
        decided = [row for row in list_approval_requests() if row["status"] != "PENDING"]
    except Exception as exc:
        st.error("Could not reach the database. Check that PostgreSQL is running and that .env is correct.")
        st.caption(str(exc)[:200])
        return

    try:
        approval_audit_rows = recent_log(500)
    except Exception as exc:
        approval_audit_rows = []
        st.warning("Audit evidence could not be retrieved. Missing checks will be shown as not recorded.")
        st.caption(str(exc)[:150])

    my_pending = []
    workflow_by_id = {}
    workflow_error = None
    for request in all_pending:
        try:
            workflow = get_approval_workflow(request["id"])
            workflow_by_id[str(request["id"])] = workflow
            current = workflow.get("current_stage")
            if current and role_can_act(user_role, current.get("required_role")):
                my_pending.append(request)
        except Exception as exc:
            workflow_error = str(exc)[:200]

    if workflow_error:
        st.error("The approval workflow could not be loaded. No approval actions are available until the database workflow table is ready.")
        st.caption(workflow_error)
        return

    approved_count = sum(1 for row in decided if row["status"] == "APPROVED")
    rejected_count = sum(1 for row in decided if row["status"] == "REJECTED")
    metric1, metric2, metric3 = st.columns(3)
    metric1.metric("Awaiting your stage", len(my_pending))
    metric2.metric("Fully approved", approved_count)
    metric3.metric("Rejected", rejected_count)

    st.info(f"Signed in as {role_label}. You can act only when an invoice reaches your assigned stage. AI recommendations remain advisory.")

    queue_tab, history_tab, payments_tab = st.tabs(
        [   "Pending review (" + str(len(my_pending)) + ")",
            "Decision history (" + str(len(decided)) + ")",
            "Payment schedule",
        ]
    )

    with queue_tab:
        st.subheader("Invoices awaiting your decision")
        if not my_pending:
            st.success("There are no invoices waiting at your approval stage.")

        for req in my_pending:
            request_id = str(req["id"])
            file_name = req["file_name"]
            workflow = workflow_by_id.get(request_id) or get_approval_workflow(req["id"])
            stages = workflow.get("stages", [])
            current = workflow.get("current_stage") or {}
            needs_review = req["recommendation"] == "NEEDS_HUMAN_REVIEW"

            with st.container(border=True):
                header_left, header_right = st.columns([3, 1])
                with header_left:
                    st.markdown("### Review request #" + request_id)
                    st.caption(file_name)
                    st.caption("Current stage: " + str(current.get("stage_label") or "Unknown"))
                with header_right:
                    if needs_review:
                        st.warning("Human review needed")
                    else:
                        st.success("No issue flagged by AI")

                st.markdown("**Approval progress**")
                progress_rows = [
                    {
                        "Stage": row.get("stage_label"),
                        "Assigned role": str(row.get("required_role") or "").replace("_", " ").title(),
                        "Status": row.get("status"),
                        "Decided by": row.get("decided_by") or "—",
                        "Decision time": str(row.get("decided_at") or "—"),
                        "Note": row.get("decision_note") or "—",
                    }
                    for row in stages
                ]
                st.dataframe(progress_rows, use_container_width=True, hide_index=True)
                st.divider()

                detail_left, detail_right = st.columns([1, 1.15], gap="large")
                with detail_left:
                    st.markdown("**AI assessment**")
                    review_reason_text = req.get("review_reason") or ""
                    if review_reason_text:
                        render_reasons(review_reason_text)
                    elif needs_review:
                        render_reasons("No specific reason was recorded.")
                    else:
                        st.success("The agent found no blocking issues in its checks.")

                    render_approval_evidence(file_name, approval_audit_rows)
                    st.divider()
                    if req.get("summary"):
                        st.markdown("**Agent summary**")
                        st.write(req["summary"])
                    else:
                        st.caption("The agent did not provide a summary.")
                    st.caption("AI recommendation: " + str(req["recommendation"]))

                with detail_right:
                    st.markdown("**Invoice details extracted by AI**")
                    show_invoice(file_name)
                    with st.expander("View original invoice and download"):
                        show_original(file_name, request_id)

                st.divider()
                st.markdown("**Your stage decision · " + str(current.get("stage_label") or role_label) + "**")
                note = st.text_input(
                    "Reviewer note (optional)",
                    key="note_" + request_id + "_" + user_role,
                    placeholder="Explain your decision or note any follow-up needed...",
                )
                action_left, action_right, _ = st.columns([1, 1, 2])

                if action_left.button(
                    "Approve this stage",
                    type="primary",
                    key="approve_stage_" + request_id + "_" + user_role,
                    use_container_width=True,
                ):
                    st.session_state["pending_decision"] = {
                        "request_id": req["id"],
                        "decision": "APPROVED",
                        "file_name": file_name,
                        "username": user["username"],
                        "user_role": user_role,
                        "note": note,
                    }
                    st.rerun()

                if action_right.button(
                    "Reject invoice",
                    type="secondary",
                    key="reject_stage_" + request_id + "_" + user_role,
                    use_container_width=True,
                ):
                    st.session_state["pending_decision"] = {
                        "request_id": req["id"],
                        "decision": "REJECTED",
                        "file_name": file_name,
                        "username": user["username"],
                        "user_role": user_role,
                        "note": note,
                    }
                    st.rerun()                

    with history_tab:
        st.subheader("Completed approval workflows")
        if decided:
            history_rows = []
            for row in decided:
                try:
                    workflow = get_approval_workflow(row["id"])
                    stages = workflow.get("stages", [])
                    stage_summary = " → ".join(
                        str(stage.get("stage_label")) + ": " + str(stage.get("status"))
                        for stage in stages
                    ) if stages else "Legacy single-stage decision"
                except Exception:
                    stage_summary = "Stage history unavailable"
                history_rows.append({
                    "Request": row["id"],
                    "Invoice": row["file_name"],
                    "AI recommendation": row["recommendation"],
                    "Flagged for": short_reasons(row.get("review_reason")),
                    "Approval stages": stage_summary,
                    "Final decision": row["status"],
                    "Final reviewer": row.get("decided_by"),
                    "Decision time": row.get("decided_at"),
                    "Reviewer note": row.get("decision_note"),
                })
            st.dataframe(history_rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No completed approval workflows have been recorded yet.")

    with payments_tab:
        _render_payment_schedule_tab(user)


# ==================================================
# AUDIT PAGE
# ==================================================

def audit_page(user):
    require_role(user, ["admin"])
    st.markdown("<div class='page-eyebrow'>ADMINISTRATION AND CONTROL</div>", unsafe_allow_html=True)
    st.title("Audit & activity center")
    st.caption("A searchable record of system activity, AI operations, vendor uploads and human decisions.")

    limit = st.slider("Number of recent events to retrieve", min_value=20, max_value=500, value=100, step=20)
    try:
        all_rows = recent_log(limit)
    except Exception as exc:
        st.error("Could not reach the database.")
        st.caption(str(exc)[:200])
        return

    for row in all_rows:
        row["_category"] = audit_category(row.get("step", ""))

    ai_count = sum(1 for row in all_rows if row["_category"] in ("AI tools", "AI agent"))
    access_count = sum(1 for row in all_rows if row["_category"] == "Access")
    decision_count = sum(1 for row in all_rows if row["_category"] == "Human decisions")

    st.markdown("### Activity overview")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Events retrieved", len(all_rows))
    c2.metric("AI activities", ai_count)
    c3.metric("Human decisions", decision_count)
    c4.metric("Access events", access_count)

    st.divider()
    st.markdown("### Explore audit records")
    filter_left, filter_right = st.columns([1, 1.4])
    categories = ["All categories", "AI tools", "AI agent", "Human decisions", "Access", "Vendor activity", "System"]

    with filter_left:
        selected_category = st.selectbox("Filter by event category", categories)
    with filter_right:
        search_query = st.text_input(
            "Search audit records",
            placeholder="Search by event, user, invoice, or detail...",
        ).strip().lower()

    filtered_rows = list(all_rows)
    if selected_category != "All categories":
        filtered_rows = [row for row in filtered_rows if row["_category"] == selected_category]
    if search_query:
        filtered_rows = [
            row for row in filtered_rows
            if search_query in " ".join([
                str(row.get("id", "")),
                str(row.get("time", "")),
                str(row.get("step", "")),
                str(row.get("detail", {})),
            ]).lower()
        ]

    st.caption(str(len(filtered_rows)) + " matching events out of " + str(len(all_rows)) + " retrieved events.")
    if filtered_rows:
        st.download_button(
            "Download filtered audit report (CSV)",
            data=create_audit_csv(filtered_rows),
            file_name="invoice_audit_report.csv",
            mime="text/csv",
            key="download_audit_csv",
        )

    st.divider()
    st.markdown("### Recent activity")
    if not filtered_rows:
        st.info("No events match your current filters. Try a different search.")
    else:
        display_rows = [
            {
                "ID": row.get("id"),
                "Time": str(row.get("time", "")),
                "Category": row["_category"],
                "Event": row.get("step", ""),
                "Details": json.dumps(row.get("detail", {}), ensure_ascii=False, default=str)[:350],
            }
            for row in filtered_rows
        ]
        st.dataframe(display_rows, use_container_width=True, hide_index=True, height=400)
        st.divider()
        st.markdown("### Event inspector")
        event_options = {}
        for row in filtered_rows:
            label = "#" + str(row.get("id")) + " · " + str(row.get("step")) + " · " + str(row.get("time"))
            event_options[label] = row
        selected_event = st.selectbox("Select an event to inspect", list(event_options.keys()))
        event = event_options[selected_event]
        with st.container(border=True):
            st.markdown("**Event #" + str(event.get("id")) + "**")
            event_col1, event_col2 = st.columns(2)
            with event_col1:
                st.markdown("**Event type**")
                st.write(event.get("step", "Unknown"))
            with event_col2:
                st.markdown("**Category**")
                st.write(event.get("_category", "System"))
            st.markdown("**Timestamp**")
            st.write(str(event.get("time", "Unknown")))
            st.divider()
            st.markdown("**Recorded event details**")
            st.json(event.get("detail", {}))

    with st.expander("About the audit system"):
        st.markdown(
            "The audit trail provides a record of actions taken by the application and its AI agent. "
            "AI tool calls, invoice-related activity, human decisions and authentication events can be "
            "inspected. Records are retrieved from the existing audit database."
        )


# ==================================================
# MAIN
# ==================================================

user = st.session_state.get("user")
if user is None:
    login_screen()
    st.stop()

st.sidebar.markdown("## 🧾 Invoice agent")
st.sidebar.caption("Smart invoice management")
st.sidebar.divider()
st.sidebar.markdown("**Current workspace**")

available_pages = ROLE_PAGES[user["role"]]
if len(available_pages) > 1:
    page = st.sidebar.selectbox("Select workspace", available_pages, key="admin_workspace")
else:
    page = available_pages[0]

sidebar_page_html = (
    '<div style="background:rgba(255,255,255,0.10);'
    'border-left:4px solid #8F95FF;'
    'padding:13px;border-radius:8px;'
    'color:#FFFFFF;font-weight:600;">'
    + page
    + '</div>'
)
st.sidebar.markdown(sidebar_page_html, unsafe_allow_html=True)
st.sidebar.write("")
st.sidebar.markdown("**Your account**")
st.sidebar.markdown(user["full_name"])
st.sidebar.caption(user["role"].capitalize())
st.sidebar.divider()

if st.sidebar.button("Log out", use_container_width=True):
    save_log("auth:logout", {"user": user["username"]})
    st.session_state.pop("user", None)
    st.rerun()

if page == "Upload invoice":
    upload_page(user)
elif page == "Approvals":
    approvals_page(user)
elif page == "Purchase Orders":
    render_po_page(user)
elif page == "Audit log":
    audit_page(user)
elif page == "Goods Receipts":
    render_grn_page(user)
elif page == "Finance workspace":
    render_finance_page(user)
