"""Evidence-based verification summary for pending invoice approvals.

This module reads existing audit events and renders only checks that have
recorded evidence. Budget remains unverified unless an explicit budget event
or recognised budget finding exists.
"""

from __future__ import annotations

import json
from typing import Any


_GRN_MISSING_CODES = {
    "MISSING_GOODS_RECEIPT",
    "MISSING_GRN",
    "NO_GOODS_RECEIPT",
}
_GRN_SHORTAGE_CODES = {
    "GRN_QUANTITY_SHORTAGE",
    "GOODS_RECEIPT_QUANTITY_SHORTAGE",
}
_BUDGET_EXCEEDED_CODES = {
    "DEPARTMENT_BUDGET_EXCEEDED",
    "BUDGET_LIMIT_EXCEEDED",
    "BUDGET_EXCEEDED",
}
_BUDGET_UNMAPPED_CODES = {
    "DEPARTMENT_UNMAPPED",
    "UNMAPPED_DEPARTMENT",
    "BUDGET_DEPARTMENT_NOT_FOUND",
}
_BUDGET_PASSED_CODES = {
    "DEPARTMENT_BUDGET_WITHIN_LIMIT",
    "BUDGET_WITHIN_LIMIT",
    "BUDGET_VALIDATED",
}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _event_detail(event: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {}
    return _as_dict(event.get("detail"))


def _event_result(event: dict[str, Any] | None) -> dict[str, Any]:
    if not event:
        return {}
    return _as_dict(_event_detail(event).get("result"))


def _latest_event(events: list[dict[str, Any]], step_names: set[str]) -> dict[str, Any] | None:
    matches = [event for event in events if str(event.get("step") or "") in step_names]
    if not matches:
        return None

    def sort_key(event: dict[str, Any]) -> tuple[int, str]:
        try:
            event_id = int(event.get("id") or 0)
        except (TypeError, ValueError):
            event_id = 0
        return event_id, str(event.get("time") or "")

    return max(matches, key=sort_key)


def build_approval_evidence(file_name: str, audit_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Build conservative status cards from saved events for one invoice."""
    matching_events: list[dict[str, Any]] = []
    for row in audit_rows or []:
        if not isinstance(row, dict):
            continue
        detail = _event_detail(row)
        if str(detail.get("file") or "") == str(file_name):
            matching_events.append(row)

    read_event = _latest_event(matching_events, {"tool:read_invoice"})
    math_event = _latest_event(matching_events, {"tool:check_invoice_math"})
    po_event = _latest_event(matching_events, {"tool:lookup_po"})
    vendor_event = _latest_event(matching_events, {"tool:check_vendor_matches_po"})
    dataset_event = _latest_event(matching_events, {"tool:check_dataset_rules"})
    budget_event = _latest_event(
        matching_events,
        {
            "tool:check_department_budget",
            "tool:check_budget",
            "tool:validate_budget",
            "budget:checked",
            "budget:validated",
        },
    )
    matching_event = _latest_event(
        matching_events,
        {"matcher:three_way_match"},
    )

    read_result = _event_result(read_event)
    math_result = _event_result(math_event)
    po_result = _event_result(po_event)
    vendor_result = _event_result(vendor_event)
    dataset_result = _event_result(dataset_event)

    findings_value = dataset_result.get("findings", [])
    findings = {
        str(code).strip().upper()
        for code in findings_value
        if code is not None
    } if isinstance(findings_value, list) else set()

    # Extraction
    if read_event is None:
        extraction = ("Not recorded", "info", "No invoice-reading event was found for this request.")
    elif read_result.get("error"):
        extraction = ("Failed", "issue", str(read_result.get("error")))
    else:
        invoice_number = read_result.get("invoice_number") or "number not recorded"
        extraction = ("Passed", "passed", f"Invoice data was extracted ({invoice_number}).")

    # Arithmetic
    math_ok = math_result.get("math_ok")
    if math_event is None:
        arithmetic = ("Not recorded", "info", "No arithmetic-check event was found.")
    elif math_ok is True:
        arithmetic = ("Passed", "passed", "The arithmetic tool returned math_ok = true.")
    elif math_ok is False:
        issues = math_result.get("issues") or []
        arithmetic = ("Issue found", "issue", str(issues) if issues else "The arithmetic check failed.")
    else:
        arithmetic = ("Inconclusive", "warning", "The tool ran but did not return a clear arithmetic result.")

    # PO lookup
    po_status = str(po_result.get("status") or "").lower()
    po_object = _as_dict(po_result.get("po"))
    po_number = po_object.get("po_number") or _event_detail(po_event).get("po_number")
    if po_event is None:
        purchase_order = ("Not recorded", "info", "No PO lookup event was found.")
    elif po_status == "found":
        purchase_order = ("Found" + (f" · {po_number}" if po_number else ""), "passed", "A matching PO was found in procurement reference data.")
    elif po_status in {"ambiguous", "guessed"}:
        purchase_order = ("Needs confirmation", "warning", str(po_result.get("note") or "The PO match was not definitive."))
    else:
        purchase_order = ("Not found", "issue", str(po_result.get("note") or "The PO could not be matched."))

    # Vendor comparison is conditional on a confirmed PO.
    vendor_status = str(vendor_result.get("status") or "").lower()
    if vendor_event is not None and vendor_status == "match":
        vendor = ("Matched", "passed", str(vendor_result.get("note") or "Vendor matches the PO."))
    elif vendor_event is not None and vendor_status == "mismatch":
        vendor = ("Mismatch", "issue", str(vendor_result.get("note") or "Vendor does not match the PO."))
    elif vendor_event is not None:
        vendor = ("Could not verify", "warning", str(vendor_result.get("note") or "Vendor comparison was inconclusive."))
    elif po_status != "found":
        vendor = ("Not run", "info", "Vendor-to-PO comparison requires a confirmed PO.")
    else:
        vendor = ("Not recorded", "warning", "A PO was found, but no vendor-comparison event was recorded.")

    # GRN evidence comes from the deterministic dataset rule output. Do not
    # claim a successful receipt match if the PO was not found or rules did not run.
    if po_status != "found":
        grn = ("Not assessed", "info", "A confirmed PO is required before GRN matching can be assessed.")
    elif dataset_event is None:
        grn = ("Not recorded", "warning", "No dataset-rule result was recorded for this request.")
    elif findings & _GRN_MISSING_CODES:
        grn = ("Missing receipt", "issue", "The PO has no accepted goods-receipt record.")
    elif findings & _GRN_SHORTAGE_CODES:
        grn = ("Quantity shortage", "issue", "The invoice quantity exceeds the accepted receipt quantity.")
    else:
        grn = ("No GRN exception flagged", "info", "Dataset rules reported no GRN exception; inspect the PO/GRN records before approval.")

    # Budget: prefer the explicit department-budget tool result. Its contract
    # uses budget_ok=True/False/None rather than a status string. A None value
    # must remain unverified; it must never be interpreted as zero consumption.
    if budget_event is not None:
        budget_result = _event_result(budget_event)
        budget_note = str(budget_result.get("note") or "").strip()
        budget_ok = budget_result.get("budget_ok")

        if budget_ok is True:
            budget = (
                "Within limit",
                "passed",
                budget_note or "The department budget checker confirmed sufficient remaining budget.",
            )
        elif budget_ok is False:
            budget = (
                "Limit exceeded",
                "issue",
                budget_note or "The department budget checker found that the invoice exceeds the remaining budget.",
            )
        elif budget_ok is None and "budget_ok" in budget_result:
            budget = (
                "Not verified",
                "warning",
                budget_note or "The department budget could not be verified.",
            )
        else:
            budget_status = str(
                budget_result.get("status")
                or budget_result.get("recommendation")
                or ""
            ).upper()
            if budget_status in {"PASSED", "WITHIN_LIMIT", "OK", "READY"}:
                budget = ("Within limit", "passed", budget_note or "Budget validation was recorded as successful.")
            elif budget_status in {"EXCEEDED", "FAILED"}:
                budget = ("Limit exceeded", "issue", budget_note or "Budget validation found an over-limit amount.")
            elif budget_status in {"NOT_VERIFIED", "UNMAPPED", "UNKNOWN", "INCOMPLETE"}:
                budget = ("Not verified", "warning", budget_note or "The department budget could not be verified.")
            elif budget_status == "NEEDS_HUMAN_REVIEW":
                budget = ("Needs review", "issue", budget_note or "Budget validation requires human review.")
            else:
                budget = ("Inconclusive", "warning", "A budget event exists but has no recognised result.")
    elif findings & _BUDGET_EXCEEDED_CODES:
        budget = ("Limit exceeded", "issue", "The recorded budget validation found an over-limit amount.")
    elif findings & _BUDGET_UNMAPPED_CODES:
        budget = ("Not verified", "warning", "The PO has no confirmed department/cost-centre mapping.")
    elif findings & _BUDGET_PASSED_CODES:
        budget = ("Within limit", "passed", "An explicit budget validation result was recorded.")
    else:
        budget = ("Not verified", "warning", "No department-budget validation result was recorded for this invoice.")

    # Three-way matcher evidence is kept separate from the agent's dataset rules.
    matching_result = _event_result(matching_event)
    matching_outcome = str(matching_result.get("matching_result") or "").upper()
    matching_findings = matching_result.get("discrepancies")
    if not isinstance(matching_findings, list):
        matching_findings = []

    if matching_event is None:
        matching = ("Not recorded", "warning", "No three-way matching event was recorded for this invoice.")
    elif matching_outcome == "NO_DISCREPANCIES_FOUND" and not matching_findings:
        matching = ("No discrepancies", "passed", "The matcher found no discrepancies. Human approval is still required.")
    elif matching_findings or matching_outcome == "DISCREPANCIES_FOUND":
        finding_details = [
            str(item.get("type") or "ISSUE") + ": " + str(item.get("details") or "")
            for item in matching_findings[:5]
            if isinstance(item, dict)
        ]
        matching = (
            "Discrepancies found",
            "issue",
            "; ".join(finding_details) or "The matcher flagged this invoice for human review.",
        )
    else:
        matching = ("Inconclusive", "warning", "The matcher event did not contain a recognised matching result.")

    cards = [
        ("Invoice extraction", extraction),
        ("Arithmetic", arithmetic),
        ("PO lookup", purchase_order),
        ("Vendor matching", vendor),
        ("GRN verification", grn),
        ("Three-way matching", matching),
        ("Budget validation", budget),
    ]

    return [
        {"name": name, "status": values[0], "kind": values[1], "detail": values[2]}
        for name, values in cards
    ]


def render_approval_evidence(file_name: str, audit_rows: list[dict[str, Any]]) -> None:
    """Render a compact verification checklist in an approval card."""
    import streamlit as st

    st.markdown("**Verification checklist**")
    st.caption("Statuses are based on saved tool events. Unrecorded checks are not treated as passed.")

    evidence = build_approval_evidence(file_name, audit_rows)
    for start in range(0, len(evidence), 2):
        left, right = st.columns(2, gap="medium")
        for column, item in ((left, evidence[start]), (right, evidence[start + 1] if start + 1 < len(evidence) else None)):
            if item is None:
                continue
            with column:
                with st.container(border=True):
                    st.markdown(f"**{item['name']}**")
                    if item["kind"] == "passed":
                        st.success(item["status"])
                    elif item["kind"] == "issue":
                        st.error(item["status"])
                    elif item["kind"] == "warning":
                        st.warning(item["status"])
                    else:
                        st.info(item["status"])
                    st.caption(item["detail"])

    st.caption("A human approver remains responsible for the final decision. Checks without recorded evidence are never treated as passed.")
