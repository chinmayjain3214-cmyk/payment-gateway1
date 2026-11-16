"""Verify the vendor-facing message templates in agent.py."""

from agent import _build_vendor_message


CASES = [
    (["MISSING_PO_REFERENCE"],         "purchase order"),
    (["PO_REFERENCE_UNMAPPED"],        "does not match"),
    (["VENDOR_PO_MISMATCH"],           "vendor name"),
    (["VENDOR_GSTIN_MISMATCH"],        "GSTIN"),
    (["INVOICE_ARITHMETIC_MISMATCH"],  "do not add up"),
    (["PO_UNIT_PRICE_MISMATCH"],       "unit price"),
    (["GRN_QUANTITY_SHORTAGE"],        "quantity"),
    (["MISSING_GOODS_RECEIPT"],        "goods receipt"),
    (["INCOMPLETE_EXTRACTION"],        "could not be read"),
    (["LOW_DOCUMENT_QUALITY"],         "scan"),
]


def run():
    print("Testing _build_vendor_message templates\n")
    passed = 0
    for codes, fragment in CASES:
        msg = _build_vendor_message(codes)
        assert msg is not None, f"No message for {codes}"
        assert fragment.lower() in msg.lower(), (
            f"{codes[0]}: expected '{fragment}' in message, got: {msg}"
        )
        print(f"  ✓ {codes[0]}")
        print(f"    → {msg[:80]}")
        passed += 1

    # Fallback path for an unknown code
    fallback = _build_vendor_message(["SOME_UNKNOWN_CODE"])
    assert fallback is not None
    assert "flagged for human review" in fallback.lower()
    print("\n  ✓ fallback for unknown code")
    print(f"    → {fallback}")

    # Empty findings must return None (no message)
    assert _build_vendor_message([]) is None
    print("  ✓ empty findings returns None")

    print(f"\n✅ {passed}/{passed} templates OK")


if __name__ == "__main__":
    try:
        run()
    except AssertionError as exc:
        print(f"\n❌ FAILED: {exc}")
        raise