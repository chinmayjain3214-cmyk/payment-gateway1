import json

import pytest

from record_store import (
    InvalidPOIdError,
    RecordConflictError,
    load_record,
    normalize_po_id,
    record_path,
    save_goods_receipt,
    save_invoice,
    save_purchase_order,
)


def test_normalize_po_id_accepts_numeric_and_po_number():
    assert normalize_po_id(118) == 118
    assert normalize_po_id("118") == 118
    assert normalize_po_id("PO-118") == 118


@pytest.mark.parametrize("value", [None, "", "PO-ABC", 0, -1, True])
def test_normalize_po_id_rejects_invalid_values(value):
    with pytest.raises(InvalidPOIdError):
        normalize_po_id(value)


def test_save_records_use_requested_filenames(tmp_path):
    po_path = save_purchase_order(
        "PO-118", {"po_number": "PO-118", "total_amount": 5900}, base_dir=tmp_path
    )
    invoice_path = save_invoice(
        118,
        {"invoice_number": "INV-118", "vendor_id": "VEN-118", "total_amount": 5900},
        base_dir=tmp_path,
    )
    grn_path = save_goods_receipt(
        118,
        {"grn_number": "GRN-118", "status": "ACCEPTED"},
        base_dir=tmp_path,
    )

    assert po_path == record_path("po", 118, base_dir=tmp_path)
    assert invoice_path == record_path("invoice", 118, base_dir=tmp_path)
    assert grn_path == record_path("grn", 118, base_dir=tmp_path)
    assert po_path.name == "po_118.json"
    assert invoice_path.name == "inv_118.json"
    assert grn_path.name == "grn_118.json"

    assert json.loads(po_path.read_text(encoding="utf-8"))["po_id"] == 118
    assert load_record("invoice", 118, base_dir=tmp_path)["record_id"] == "inv_118"
    assert load_record("grn", 118, base_dir=tmp_path)["record_id"] == "grn_118"


def test_po_can_be_updated_for_same_po_id(tmp_path):
    save_purchase_order(118, {"po_number": "PO-118", "status": "DRAFT"}, base_dir=tmp_path)
    save_purchase_order(118, {"po_number": "PO-118", "status": "APPROVED"}, base_dir=tmp_path)
    saved = load_record("po", 118, base_dir=tmp_path)
    assert saved["status"] == "APPROVED"


def test_different_invoice_for_same_po_is_not_overwritten(tmp_path):
    first = {"invoice_number": "INV-118-A", "vendor_id": 8, "total_amount": 100}
    second = {"invoice_number": "INV-118-B", "vendor_id": 8, "total_amount": 200}
    save_invoice(118, first, base_dir=tmp_path)
    with pytest.raises(RecordConflictError):
        save_invoice(118, second, base_dir=tmp_path)
    assert load_record("invoice", 118, base_dir=tmp_path)["invoice_number"] == "INV-118-A"


def test_different_grn_for_same_po_is_not_overwritten(tmp_path):
    first = {"grn_number": "GRN-118-A", "status": "PARTIALLY ACCEPTED"}
    second = {"grn_number": "GRN-118-B", "status": "ACCEPTED"}
    save_goods_receipt(118, first, base_dir=tmp_path)
    with pytest.raises(RecordConflictError):
        save_goods_receipt(118, second, base_dir=tmp_path)
    assert load_record("grn", 118, base_dir=tmp_path)["grn_number"] == "GRN-118-A"


def test_same_invoice_is_idempotent(tmp_path):
    data = {"invoice_number": "INV-118", "vendor_id": 8, "total_amount": 100}
    first = save_invoice(118, data, base_dir=tmp_path)
    second = save_invoice(118, data, base_dir=tmp_path)
    assert first == second


def test_po_id_cannot_be_reassigned_to_a_different_po_number(tmp_path):
    save_purchase_order(118, {"po_number": "PO-118", "status": "DRAFT"}, base_dir=tmp_path)
    with pytest.raises(RecordConflictError):
        save_purchase_order(118, {"po_number": "PO-999", "status": "APPROVED"}, base_dir=tmp_path)
    assert load_record("po", 118, base_dir=tmp_path)["po_number"] == "PO-118"
