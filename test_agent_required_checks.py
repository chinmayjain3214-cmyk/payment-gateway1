"""Regression tests for required PO and vendor checks in the agent safety guard.

Run from the project root with:
    python -m pytest -q test_agent_required_checks.py

All agent tools are mocked; these tests do not call Gemini or write to the database.
"""

from unittest.mock import patch

import agent


def test_required_checks_pass_file_name_and_po_to_lookup_and_vendor_check():
    file_name = "sample-invoice.pdf"
    invoice = {
        "vendor": "Delta Lab Supplies",
        "po_number": "PO-118",
        "po_reference": "PO-118",
    }
    po_result = {
        "status": "found",
        "po": {"po_number": "PO-118", "vendor": "Delta Lab Supplies"},
        "note": "Exact PO found.",
    }
    vendor_result = {"status": "match", "note": "Vendor matches PO."}
    dataset_result = {
        "recommendation": "NEEDS_HUMAN_REVIEW",
        "findings": ["MISSING_GOODS_RECEIPT"],
    }

    with (
        patch.object(agent, "read_invoice", return_value=invoice),
        patch.object(
            agent,
            "check_invoice_math",
            return_value={"math_ok": True, "issues": []},
        ),
        patch.object(agent, "lookup_po", return_value=po_result) as lookup_mock,
        patch.object(
            agent,
            "check_vendor_matches_po",
            return_value=vendor_result,
        ) as vendor_mock,
        patch.object(agent, "check_dataset_rules", return_value=dataset_result),
        patch.object(agent, "_safe_log"),
    ):
        results = agent._ensure_required_tool_checks(file_name)

    lookup_mock.assert_called_once_with(file_name, "PO-118")
    vendor_mock.assert_called_once_with(file_name, "PO-118")
    assert results["lookup_po"] == po_result
    assert results["check_vendor_matches_po"] == vendor_result
    assert results["check_dataset_rules"] == dataset_result


def test_vendor_check_is_skipped_when_po_is_not_found():
    file_name = "sample-invoice.pdf"
    invoice = {"vendor": "Delta Lab Supplies", "po_number": "PO-MISSING"}
    missing_po = {"status": "not_found", "po": None, "note": "No exact PO."}
    dataset_result = {
        "recommendation": "NEEDS_HUMAN_REVIEW",
        "findings": ["PO_REFERENCE_UNMAPPED"],
    }

    with (
        patch.object(agent, "read_invoice", return_value=invoice),
        patch.object(
            agent,
            "check_invoice_math",
            return_value={"math_ok": True, "issues": []},
        ),
        patch.object(agent, "lookup_po", return_value=missing_po) as lookup_mock,
        patch.object(agent, "check_vendor_matches_po") as vendor_mock,
        patch.object(agent, "check_dataset_rules", return_value=dataset_result),
        patch.object(agent, "_safe_log"),
    ):
        results = agent._ensure_required_tool_checks(file_name)

    lookup_mock.assert_called_once_with(file_name, "PO-MISSING")
    vendor_mock.assert_not_called()
    assert results["lookup_po"] == missing_po
    assert "check_vendor_matches_po" not in results
