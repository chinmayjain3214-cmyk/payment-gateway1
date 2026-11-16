"""Verify record_outcome attaches a vendor message when the recommendation
is NEEDS_HUMAN_REVIEW, and skips it when it is READY_FOR_APPROVAL.

Mocks the DB and tool calls; no real writes.
"""

from unittest.mock import patch

import agent


FILE = "test-integration.pdf"


def test_needs_review_writes_message():
    with patch.object(agent, "_ensure_required_tool_checks", return_value={}), \
         patch.object(agent, "get_dataset_result", return_value={
             "recommendation": "NEEDS_HUMAN_REVIEW",
             "findings": ["MISSING_PO_REFERENCE"],
         }), \
         patch.object(agent, "send_to_human_review", return_value={"queued": True}), \
         patch.object(agent, "save_approval_request", return_value=999), \
         patch.object(agent, "set_vendor_message") as mock_set:

        result = agent.record_outcome(FILE, "Test summary")

    assert result["recommendation"] == "NEEDS_HUMAN_REVIEW"
    mock_set.assert_called_once()
    args, _ = mock_set.call_args
    assert args[0] == FILE
    assert "purchase order" in args[1].lower(), (
        f"Unexpected message: {args[1]!r}"
    )
    print("  ✓ NEEDS_HUMAN_REVIEW → set_vendor_message called")
    print(f"    message: {args[1][:70]}...")


def test_ready_for_approval_skips_message():
    with patch.object(agent, "_ensure_required_tool_checks", return_value={}), \
         patch.object(agent, "get_dataset_result", return_value={
             "recommendation": "READY_FOR_APPROVAL",
             "findings": [],
         }), \
         patch.object(agent, "send_to_human_review", return_value={"queued": True}), \
         patch.object(agent, "save_approval_request", return_value=1000), \
         patch.object(agent, "set_vendor_message") as mock_set:

        result = agent.record_outcome(FILE, "Test summary")

    assert result["recommendation"] == "READY_FOR_APPROVAL"
    mock_set.assert_not_called()
    print("  ✓ READY_FOR_APPROVAL → set_vendor_message NOT called")


if __name__ == "__main__":
    print("Integration test: record_outcome → set_vendor_message\n")
    test_needs_review_writes_message()
    test_ready_for_approval_skips_message()
    print("\n✅ Both integration cases OK")