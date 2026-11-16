import json
from pathlib import Path

import matcher


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def setup_records(root: Path, *, accepted=2, invoice_qty=2, invoice_price=10.0):
    write_json(root / "data/purchase_orders/po_119.json", {
        "po_id": 119,
        "po_number": "PO-119",
        "vendor_id": "VEN-102",
        "vendor_name": "Acme Traders",
        "status": "PENDING",
        "price_tolerance_percent": 1.0,
        "items": [{
            "description": "Laser Toner Cartridge",
            "quantity_ordered": 2,
            "approved_unit_price": 10.0,
        }],
        "total_amount": 23.6,
    })
    write_json(root / "data/goods_receipts/grn_119.json", {
        "po_id": 119,
        "po_number": "PO-119",
        "status": "ACCEPTED",
        "items": [{
            "description": "Laser Toner Cartridge",
            "quantity_received": accepted,
            "quantity_accepted": accepted,
            "quantity_rejected": 0,
        }],
        "total_pending_inspection": 0,
    })
    write_json(root / "data/invoices/inv_119.json", {
        "po_id": 119,
        "po_number": "PO-119",
        "vendor_id": "VEN-102",
        "vendor": "Acme Traders",
        "invoice_number": "INV-119",
        "total_amount": 23.6,
        "items": [{
            "description": "Laser Toner Cartridge",
            "quantity": invoice_qty,
            "unit_price": invoice_price,
        }],
    })


def test_matching_reads_app_schema_and_stays_pending_for_human(tmp_path):
    setup_records(tmp_path)

    reports = matcher.process_orders_sequentially(tmp_path)

    assert len(reports) == 1
    report = reports[0]
    assert report["matching_result"] == "NO_DISCREPANCIES_FOUND"
    assert report["status"] == "NEEDS_HUMAN_REVIEW"
    assert report["recommendation"] == "MATCHED_PENDING_HUMAN_APPROVAL"
    assert report["discrepancies"] == []
    audit_files = list((tmp_path / "data/audit_reports").glob("audit_*.json"))
    assert len(audit_files) == 1
    saved = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert saved["status"] == "NEEDS_HUMAN_REVIEW"


def test_flags_invoice_quantity_above_accepted_grn(tmp_path):
    setup_records(tmp_path, accepted=1, invoice_qty=2)

    report = matcher.process_orders_sequentially(tmp_path)[0]

    finding_types = {item["type"] for item in report["discrepancies"]}
    assert "INVOICE_EXCEEDS_ACCEPTED_GRN_QUANTITY" in finding_types
    assert report["status"] == "NEEDS_HUMAN_REVIEW"


def test_flags_unit_price_exceeding_po_tolerance(tmp_path):
    setup_records(tmp_path, invoice_price=10.5)

    report = matcher.process_orders_sequentially(tmp_path)[0]

    finding_types = {item["type"] for item in report["discrepancies"]}
    assert "UNIT_PRICE_EXCEEDED" in finding_types


def test_ignores_extraction_cache_json_files(tmp_path):
    setup_records(tmp_path)
    write_json(tmp_path / "data/invoices/upload_123.pdf.json", {
        "invoice_number": "CACHE-ONLY",
        "po_id": 119,
    })

    reports = matcher.process_orders_sequentially(tmp_path)

    assert len(reports) == 1
    assert reports[0]["invoice_number"] == "INV-119"


def test_vendor_name_mismatch_is_flagged_even_if_id_matches(tmp_path):
    setup_records(tmp_path)
    invoice_path = tmp_path / "data/invoices/inv_119.json"
    invoice = json.loads(invoice_path.read_text(encoding="utf-8"))
    invoice["vendor"] = "Different Supplier"
    invoice_path.write_text(json.dumps(invoice), encoding="utf-8")

    report = matcher.process_orders_sequentially(tmp_path)[0]

    assert "VENDOR_NAME_MISMATCH" in {item["type"] for item in report["discrepancies"]}


def test_missing_grn_is_reported(tmp_path):
    setup_records(tmp_path)
    (tmp_path / "data/goods_receipts/grn_119.json").unlink()

    report = matcher.process_orders_sequentially(tmp_path)[0]

    assert "MISSING_GRN" in {item["type"] for item in report["discrepancies"]}


def test_duplicate_invoice_number_for_same_vendor_is_reported(tmp_path):
    setup_records(tmp_path)
    duplicate = json.loads((tmp_path / "data/invoices/inv_119.json").read_text(encoding="utf-8"))
    duplicate["po_id"] = 120
    write_json(tmp_path / "data/purchase_orders/po_120.json", {
        "po_id": 120,
        "vendor_id": "VEN-102",
        "vendor_name": "Acme Traders",
        "items": [],
    })
    write_json(tmp_path / "data/invoices/inv_120.json", duplicate)

    reports = matcher.process_orders_sequentially(tmp_path)

    assert len(reports) == 2
    assert all(
        "DUPLICATE_INVOICE" in {item["type"] for item in report["discrepancies"]}
        for report in reports
    )


def test_process_invoice_record_matches_only_requested_canonical_invoice(tmp_path):
    setup_records(tmp_path)
    write_json(tmp_path / "data/purchase_orders/po_120.json", {
        "po_id": 120,
        "vendor_id": "VEN-120",
        "vendor_name": "Other Vendor",
        "items": [],
    })
    write_json(tmp_path / "data/invoices/inv_120.json", {
        "po_id": 120,
        "vendor_id": "VEN-120",
        "invoice_number": "INV-120",
        "total_amount": 99,
        "items": [],
    })

    invoice_path = tmp_path / "data/invoices/inv_119.json"
    report = matcher.process_invoice_record(invoice_path, base_dir=tmp_path)

    assert report["invoice_number"] == "INV-119"
    assert report["status"] == "NEEDS_HUMAN_REVIEW"
    assert Path(report["audit_report_path"]).name.startswith("audit_INV-119_")
    audit_files = list((tmp_path / "data/audit_reports").glob("audit_*.json"))
    assert len(audit_files) == 1


def test_process_invoice_record_rejects_extraction_cache_path(tmp_path):
    setup_records(tmp_path)
    cache_path = tmp_path / "data/invoices/upload_abc.pdf.json"
    write_json(cache_path, {"invoice_number": "CACHE-1", "po_id": 119})

    try:
        matcher.process_invoice_record(cache_path, base_dir=tmp_path)
    except ValueError as exc:
        assert "canonical" in str(exc).lower()
    else:
        raise AssertionError("Expected extraction-cache path to be rejected")