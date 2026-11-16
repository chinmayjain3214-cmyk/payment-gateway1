import json

import pytest

import tools


def test_find_po_finds_saved_json_record(tmp_path, monkeypatch):
    po_dir = tmp_path / "purchase_orders"
    po_dir.mkdir()
    (po_dir / "po_205.json").write_text(
        json.dumps({
            "po_id": 205,
            "po_number": "PO-205",
            "vendor_id": "VEN-205",
            "vendor_name": "Northwind Supplies",
            "status": "PENDING",
            "items": [],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(tools, "PURCHASE_ORDER_DIR", po_dir)
    monkeypatch.setattr(tools, "load_reference_data", lambda: {"purchase_orders": []})

    result = tools.find_po("PO 205")

    assert result["status"] == "found"
    assert result["po"]["po_id"] == 205
    assert result["po"]["vendor"] == "Northwind Supplies"
    assert "saved" in result["note"].lower()


def test_find_po_still_finds_reference_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "PURCHASE_ORDER_DIR", tmp_path / "missing")
    monkeypatch.setattr(
        tools,
        "load_reference_data",
        lambda: {"purchase_orders": [{"po_number": "PO-101", "vendor_name": "Fixture Vendor"}]},
    )

    result = tools.find_po("po 101")

    assert result["status"] == "found"
    assert result["po"]["vendor"] == "Fixture Vendor"


def test_find_po_does_not_accept_partial_or_guessed_match(tmp_path, monkeypatch):
    po_dir = tmp_path / "purchase_orders"
    po_dir.mkdir()
    (po_dir / "po_205.json").write_text(
        json.dumps({"po_id": 205, "po_number": "PO-205"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(tools, "PURCHASE_ORDER_DIR", po_dir)
    monkeypatch.setattr(tools, "load_reference_data", lambda: {"purchase_orders": []})

    result = tools.find_po("PO-20")

    assert result["status"] == "not_found"
    assert result["po"] is None


def test_find_po_fails_closed_for_corrupt_saved_record(tmp_path, monkeypatch):
    po_dir = tmp_path / "purchase_orders"
    po_dir.mkdir()
    (po_dir / "po_205.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(tools, "PURCHASE_ORDER_DIR", po_dir)
    monkeypatch.setattr(tools, "load_reference_data", lambda: {"purchase_orders": []})

    with pytest.raises(ValueError, match="Could not read saved record"):
        tools.find_po("PO-205")


def test_saved_goods_receipts_are_loaded(tmp_path, monkeypatch):
    grn_dir = tmp_path / "goods_receipts"
    grn_dir.mkdir()
    (grn_dir / "grn_205.json").write_text(
        json.dumps({"po_id": 205, "po_number": "PO-205", "grn_number": "GRN-205"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(tools, "GOODS_RECEIPT_DIR", grn_dir)

    records = tools.load_saved_goods_receipts()

    assert len(records) == 1
    assert records[0]["grn_number"] == "GRN-205"
