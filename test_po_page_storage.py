import json
import sys
import types

# Streamlit is only needed when rendering UI; these tests exercise pure helpers.
sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))

from po_pages import get_next_po_id, merge_saved_purchase_orders, parse_positive_number


def test_next_po_id_continues_after_reference_dataset(tmp_path):
    records = [
        {"po_number": "PO-101"},
        {"po_number": "PO-118"},
        {"po_number": "PO-103"},
    ]
    # Use an isolated empty data directory so local POs created during UI
    # testing do not change this fixture-based expectation.
    assert get_next_po_id(records, base_dir=tmp_path) == 119


def test_next_po_id_uses_explicit_po_id_before_po_number(tmp_path):
    records = [{"po_id": 305, "po_number": "PO-118"}]
    assert get_next_po_id(records, base_dir=tmp_path) == 306


def test_next_po_id_includes_existing_canonical_files(tmp_path):
    folder = tmp_path / "data" / "purchase_orders"
    folder.mkdir(parents=True)
    (folder / "po_140.json").write_text(
        json.dumps({"po_id": 140, "po_number": "PO-140"}), encoding="utf-8"
    )
    assert get_next_po_id([], base_dir=tmp_path) == 141


def test_merge_saved_po_overlays_fixture_without_duplicate(tmp_path):
    folder = tmp_path / "data" / "purchase_orders"
    folder.mkdir(parents=True)
    (folder / "po_118.json").write_text(
        json.dumps({
            "po_id": 118,
            "record_id": "po_118",
            "po_number": "PO-118",
            "status": "PENDING",
            "total_amount": 5900,
        }),
        encoding="utf-8",
    )
    reference = {
        "purchase_orders": [
            {"po_number": "PO-118", "status": "APPROVED", "vendor_name": "Vendor A"},
            {"po_number": "PO-117", "status": "APPROVED"},
        ]
    }
    merged = merge_saved_purchase_orders(reference, base_dir=tmp_path)
    assert len(merged["purchase_orders"]) == 2
    po = next(row for row in merged["purchase_orders"] if row["po_number"] == "PO-118")
    assert po["status"] == "PENDING"
    assert po["vendor_name"] == "Vendor A"
    assert po["po_id"] == 118


def test_merge_saved_po_adds_new_record(tmp_path):
    folder = tmp_path / "data" / "purchase_orders"
    folder.mkdir(parents=True)
    (folder / "po_119.json").write_text(
        json.dumps({"po_id": 119, "po_number": "PO-119", "status": "PENDING"}),
        encoding="utf-8",
    )
    merged = merge_saved_purchase_orders({"purchase_orders": []}, base_dir=tmp_path)
    assert merged["purchase_orders"][0]["record_id"] == "po_119"


def test_po_form_accepts_blank_first_then_parses_positive_values():
    assert parse_positive_number("2", "Quantity", 1) == 2.0
    assert parse_positive_number("1,200.50", "Unit price", 1) == 1200.5


def test_po_form_rejects_missing_or_non_positive_values():
    import pytest

    for value in ("", "0", "-2", "not a number", "nan", "inf"):
        with pytest.raises(ValueError):
            parse_positive_number(value, "Quantity", 1)
