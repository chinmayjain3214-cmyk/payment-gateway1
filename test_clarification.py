"""Manual end-to-end test for the vendor clarification mechanism.

Creates a fake vendor upload, writes a vendor message, verifies it
appears in the vendor's submission list, acknowledges it, and verifies
it is cleared. Cleans up its own test data.
"""

import uuid

from db import get_connection
from db_store import (
    acknowledge_vendor_message,
    list_vendor_submissions,
    save_approval_request,
    save_log,
    set_vendor_message,
)


TEST_VENDOR = "vendor1"
TEST_FILE = "upload_test_clarification_" + uuid.uuid4().hex[:8] + ".pdf"
TEST_MESSAGE = (
    "Your invoice does not show a purchase order number. "
    "Please re-upload with the PO number clearly printed."
)


def preflight():
    """Confirm the schema migration has run."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'approval_requests'
                  AND column_name = 'vendor_message';
                """
            )
            if not cur.fetchone():
                print("❌ vendor_message column missing.")
                print("   Run: python setup_agent_tables.py")
                return False
    finally:
        conn.close()
    return True


def cleanup():
    """Remove the test rows so the demo DB stays clean."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM approval_requests WHERE file_name = %s;",
                (TEST_FILE,),
            )
            cur.execute(
                "DELETE FROM agent_log WHERE detail->>'file' = %s;",
                (TEST_FILE,),
            )
        conn.commit()
    finally:
        conn.close()


def step(label):
    print()
    print(f"── {label}")


def run():
    print("=" * 55)
    print("Vendor clarification — backend test")
    print("=" * 55)
    print(f"Vendor:  {TEST_VENDOR}")
    print(f"File:    {TEST_FILE}")

    if not preflight():
        return

    cleanup()

    step("1. Save vendor:upload event (so list_vendor_submissions finds it)")
    ok = save_log("vendor:upload", {"user": TEST_VENDOR, "file": TEST_FILE})
    assert ok, "save_log returned False"
    print("   ✓ event saved")

    step("2. Create a PENDING approval request")
    request_id = save_approval_request(
        TEST_FILE,
        "NEEDS_HUMAN_REVIEW",
        "Test summary for clarification feature.",
        "MISSING_PO_REFERENCE",
    )
    assert request_id is not None, "save_approval_request returned None"
    print(f"   ✓ request #{request_id} created")

    step("3. Attach a vendor message")
    msg_id = set_vendor_message(TEST_FILE, TEST_MESSAGE)
    assert msg_id == request_id, f"expected request #{request_id}, got {msg_id}"
    print(f"   ✓ message written to request #{msg_id}")

    step("4. Confirm list_vendor_submissions sees the message")
    submissions = list_vendor_submissions(TEST_VENDOR)
    match = next((s for s in submissions if s["file_name"] == TEST_FILE), None)
    assert match is not None, "test file not in submission list"
    assert match["status"] == "PENDING", f"status={match['status']!r}"
    assert match["vendor_message"] == TEST_MESSAGE, (
        f"message mismatch: {match.get('vendor_message')!r}"
    )
    print(f"   ✓ found in list with status={match['status']}")
    print(f"     message: {match['vendor_message'][:60]}...")

    step("5. Acknowledge the message")
    acked = acknowledge_vendor_message(request_id)
    assert acked is True, "acknowledge returned False"
    print("   ✓ acknowledge returned True")

    step("6. Confirm the message is cleared")
    submissions = list_vendor_submissions(TEST_VENDOR)
    match = next((s for s in submissions if s["file_name"] == TEST_FILE), None)
    assert match is not None, "test file disappeared from list"
    assert match["vendor_message"] is None, (
        f"message should be None, got {match['vendor_message']!r}"
    )
    print("   ✓ vendor_message is now None")

    step("7. Double-acknowledge must return False")
    acked_again = acknowledge_vendor_message(request_id)
    assert acked_again is False, "double-acknowledge should return False"
    print("   ✓ returned False as expected")

    step("8. Cleanup")
    cleanup()
    print("   ✓ test data removed")

    print()
    print("=" * 55)
    print("✅ ALL BACKEND STEPS PASSED")
    print("=" * 55)


if __name__ == "__main__":
    try:
        run()
    except AssertionError as exc:
        print(f"\n❌ FAILED: {exc}")
        raise
    except Exception as exc:
        print(f"\n❌ ERROR: {type(exc).__name__}: {exc}")
        cleanup()
        raise"""Manual end-to-end test for the vendor clarification mechanism.

Creates a fake vendor upload, writes a vendor message, verifies it
appears in the vendor's submission list, acknowledges it, and verifies
it is cleared. Cleans up its own test data.
"""

import uuid

from db import get_connection
from db_store import (
    acknowledge_vendor_message,
    list_vendor_submissions,
    save_approval_request,
    save_log,
    set_vendor_message,
)


TEST_VENDOR = "vendor1"
TEST_FILE = "upload_test_clarification_" + uuid.uuid4().hex[:8] + ".pdf"
TEST_MESSAGE = (
    "Your invoice does not show a purchase order number. "
    "Please re-upload with the PO number clearly printed."
)


def preflight():
    """Confirm the schema migration has run."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'approval_requests'
                  AND column_name = 'vendor_message';
                """
            )
            if not cur.fetchone():
                print("❌ vendor_message column missing.")
                print("   Run: python setup_agent_tables.py")
                return False
    finally:
        conn.close()
    return True


def cleanup():
    """Remove the test rows so the demo DB stays clean."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM approval_requests WHERE file_name = %s;",
                (TEST_FILE,),
            )
            cur.execute(
                "DELETE FROM agent_log WHERE detail->>'file' = %s;",
                (TEST_FILE,),
            )
        conn.commit()
    finally:
        conn.close()


def step(label):
    print()
    print(f"── {label}")


def run():
    print("=" * 55)
    print("Vendor clarification — backend test")
    print("=" * 55)
    print(f"Vendor:  {TEST_VENDOR}")
    print(f"File:    {TEST_FILE}")

    if not preflight():
        return

    cleanup()

    step("1. Save vendor:upload event (so list_vendor_submissions finds it)")
    ok = save_log("vendor:upload", {"user": TEST_VENDOR, "file": TEST_FILE})
    assert ok, "save_log returned False"
    print("   ✓ event saved")

    step("2. Create a PENDING approval request")
    request_id = save_approval_request(
        TEST_FILE,
        "NEEDS_HUMAN_REVIEW",
        "Test summary for clarification feature.",
        "MISSING_PO_REFERENCE",
    )
    assert request_id is not None, "save_approval_request returned None"
    print(f"   ✓ request #{request_id} created")

    step("3. Attach a vendor message")
    msg_id = set_vendor_message(TEST_FILE, TEST_MESSAGE)
    assert msg_id == request_id, f"expected request #{request_id}, got {msg_id}"
    print(f"   ✓ message written to request #{msg_id}")

    step("4. Confirm list_vendor_submissions sees the message")
    submissions = list_vendor_submissions(TEST_VENDOR)
    match = next((s for s in submissions if s["file_name"] == TEST_FILE), None)
    assert match is not None, "test file not in submission list"
    assert match["status"] == "PENDING", f"status={match['status']!r}"
    assert match["vendor_message"] == TEST_MESSAGE, (
        f"message mismatch: {match.get('vendor_message')!r}"
    )
    print(f"   ✓ found in list with status={match['status']}")
    print(f"     message: {match['vendor_message'][:60]}...")

    step("5. Acknowledge the message")
    acked = acknowledge_vendor_message(request_id)
    assert acked is True, "acknowledge returned False"
    print("   ✓ acknowledge returned True")

    step("6. Confirm the message is cleared")
    submissions = list_vendor_submissions(TEST_VENDOR)
    match = next((s for s in submissions if s["file_name"] == TEST_FILE), None)
    assert match is not None, "test file disappeared from list"
    assert match["vendor_message"] is None, (
        f"message should be None, got {match['vendor_message']!r}"
    )
    print("   ✓ vendor_message is now None")

    step("7. Double-acknowledge must return False")
    acked_again = acknowledge_vendor_message(request_id)
    assert acked_again is False, "double-acknowledge should return False"
    print("   ✓ returned False as expected")

    step("8. Cleanup")
    cleanup()
    print("   ✓ test data removed")

    print()
    print("=" * 55)
    print("✅ ALL BACKEND STEPS PASSED")
    print("=" * 55)


if __name__ == "__main__":
    try:
        run()
    except AssertionError as exc:
        print(f"\n❌ FAILED: {exc}")
        raise
    except Exception as exc:
        print(f"\n❌ ERROR: {type(exc).__name__}: {exc}")
        cleanup()
        raise