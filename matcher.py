"""Three-way invoice matching for the Streamlit app's canonical JSON records.

Reads:
    data/purchase_orders/po_<po_id>.json
    data/goods_receipts/grn_<po_id>.json
    data/invoices/inv_<po_id>.json

Writes timestamped reports to data/audit_reports/.

This module produces audit findings and recommendations only. It never approves
or pays an invoice; final approval remains a human decision in the application.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
PO_DIR = BASE_DIR / "data" / "purchase_orders"
GRN_DIR = BASE_DIR / "data" / "goods_receipts"
INV_DIR = BASE_DIR / "data" / "invoices"
AUDIT_DIR = BASE_DIR / "data" / "audit_reports"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _number(value: Any) -> float | None:
    """Convert a numeric field without silently treating missing data as zero."""
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _po_key(value: Any) -> str:
    """Convert 119, '119', '119.0', or 'PO-119' to filename key '119'."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    raw = str(value or "").strip()
    if raw[:2].upper() == "PO":
        raw = raw[2:].lstrip(" -_#")
    if re.fullmatch(r"\d+\.0+", raw):
        raw = raw.split(".", 1)[0]
    return re.sub(r"[^A-Za-z0-9_-]", "", raw)


def _safe_filename(value: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "invoice"))
    return cleaned.strip("._") or "invoice"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⚠️ Could not read {path}: {exc}")
        return None
    if not isinstance(value, dict):
        print(f"⚠️ Skipping {path}: expected a JSON object.")
        return None
    return value


def _invoice_items(invoice: dict[str, Any]) -> list[dict[str, Any]]:
    raw = invoice.get("items") or invoice.get("line_items") or []
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _po_items(po: dict[str, Any]) -> list[dict[str, Any]]:
    raw = po.get("items") or po.get("line_items") or []
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _grn_items(grn: dict[str, Any]) -> list[dict[str, Any]]:
    raw = grn.get("items") or grn.get("line_items") or []
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _item_description(item: dict[str, Any]) -> str:
    return str(_first_value(item.get("description"), item.get("name"), item.get("item"), "") or "")


def _item_sku(item: dict[str, Any]) -> str:
    return str(_first_value(item.get("sku"), item.get("item_code"), item.get("product_id"), "") or "")


def _item_quantity(item: dict[str, Any], kind: str) -> float | None:
    if kind == "po":
        value = _first_value(
            item.get("quantity_ordered"), item.get("quantity"), item.get("qty"), item.get("count")
        )
    elif kind == "invoice":
        value = _first_value(item.get("quantity"), item.get("qty"), item.get("count"))
    elif kind == "grn_received":
        value = _first_value(item.get("quantity_received"), item.get("received_quantity"))
    elif kind == "grn_accepted":
        value = _first_value(item.get("quantity_accepted"), item.get("accepted_quantity"))
    elif kind == "grn_rejected":
        value = _first_value(item.get("quantity_rejected"), item.get("rejected_quantity"))
    else:
        return None
    return _number(value)


def _item_unit_price(item: dict[str, Any], kind: str) -> float | None:
    if kind == "po":
        value = _first_value(
            item.get("approved_unit_price"), item.get("unit_price"), item.get("price"), item.get("rate")
        )
    else:
        value = _first_value(item.get("unit_price"), item.get("price"), item.get("rate"))
    return _number(value)


def _match_po_item(item: dict[str, Any], po_items: list[dict[str, Any]]) -> int | None:
    """Match using SKU when both sides have it; otherwise exact normalised description."""
    sku = _normalise(_item_sku(item))
    if sku:
        sku_matches = [
            index for index, po_item in enumerate(po_items)
            if _normalise(_item_sku(po_item)) == sku and _normalise(_item_sku(po_item))
        ]
        if len(sku_matches) == 1:
            return sku_matches[0]
        if len(sku_matches) > 1:
            return None

    description = _normalise(_item_description(item))
    if not description:
        return None
    matches = [
        index for index, po_item in enumerate(po_items)
        if _normalise(_item_description(po_item)) == description
    ]
    return matches[0] if len(matches) == 1 else None


def _vendor_findings(invoice: dict[str, Any], po: dict[str, Any]) -> list[dict[str, str]]:
    """Compare vendor IDs and clean company names, ignoring address blocks."""
    findings: list[dict[str, str]] = []

    invoice_vendor_id = _first_value(invoice.get("vendor_id"), invoice.get("vid"))
    po_vendor_id = _first_value(po.get("vendor_id"), po.get("vid"))
    invoice_vendor = _first_value(invoice.get("vendor"), invoice.get("vendor_name"))
    po_vendor = _first_value(po.get("vendor_name"), po.get("vendor"))

    def clean_vendor_name(value: Any) -> str:
        if isinstance(value, dict):
            value = (
                value.get("name")
                or value.get("vendor_name")
                or value.get("supplier_name")
            )
        lines = [
            line.strip()
            for line in str(value or "").replace("\r", "\n").split("\n")
            if line.strip()
        ]
        # Extractors sometimes append the address, vendor ID and GSTIN
        # after the company name. The first non-empty line is the name.
        return _normalise(lines[0]) if lines else ""

    invoice_name = clean_vendor_name(invoice_vendor)
    po_name = clean_vendor_name(po_vendor)
    invoice_id = _normalise(invoice_vendor_id)
    po_id = _normalise(po_vendor_id)

    if invoice_id and po_id:
        if invoice_id != po_id:
            findings.append({
                "type": "VENDOR_ID_MISMATCH",
                "details": (
                    f"Invoice vendor ID '{invoice_vendor_id}' does not match "
                    f"PO vendor ID '{po_vendor_id}'."
                ),
            })
        # Compare names independently as a second identity check.
        if invoice_name and po_name and invoice_name != po_name:
            findings.append({
                "type": "VENDOR_NAME_MISMATCH",
                "details": (
                    f"Invoice vendor name '{invoice_vendor}' does not match "
                    f"PO vendor name '{po_vendor}'."
                ),
            })
    elif invoice_name and po_name:
        if invoice_name != po_name:
            findings.append({
                "type": "VENDOR_MISMATCH",
                "details": (
                    f"Invoice vendor '{invoice_vendor}' does not match "
                    f"PO vendor '{po_vendor}'."
                ),
            })
    elif not invoice_id and not invoice_name:
        findings.append({
            "type": "INVOICE_VENDOR_MISSING",
            "details": (
                "The canonical invoice record does not contain "
                "a vendor ID or vendor name."
            ),
        })
    elif not po_id and not po_name:
        findings.append({
            "type": "PO_VENDOR_MISSING",
            "details": (
                "The purchase order does not contain "
                "a vendor ID or vendor name."
            ),
        })

    return findings


def _duplicate_invoice_keys(invoice_records: list[tuple[Path, dict[str, Any]]]) -> Counter:
    keys: list[tuple[str, str]] = []
    for _path, invoice in invoice_records:
        invoice_number = _normalise(invoice.get("invoice_number") or invoice.get("inv_no"))
        vendor = _normalise(
            _first_value(invoice.get("vendor_id"), invoice.get("vendor"), invoice.get("vendor_name"))
        )
        if invoice_number:
            keys.append((vendor, invoice_number))
    return Counter(keys)


def _build_report(
    invoice_path: Path,
    invoice: dict[str, Any],
    po: dict[str, Any] | None,
    grn: dict[str, Any] | None,
    duplicate_keys: Counter,
) -> dict[str, Any]:
    invoice_number = _first_value(invoice.get("invoice_number"), invoice.get("inv_no"))
    po_id = _first_value(invoice.get("po_id"), invoice.get("purchase_order_id"), invoice.get("po_number"))
    findings: list[dict[str, str]] = []

    if not invoice_number:
        findings.append({
            "type": "MISSING_INVOICE_NUMBER",
            "details": "The canonical invoice record has no invoice number.",
        })

    vendor_key = _normalise(
        _first_value(invoice.get("vendor_id"), invoice.get("vendor"), invoice.get("vendor_name"))
    )
    invoice_key = _normalise(invoice_number)
    if invoice_key and duplicate_keys[(vendor_key, invoice_key)] > 1:
        findings.append({
            "type": "DUPLICATE_INVOICE",
            "details": f"Invoice '{invoice_number}' appears in more than one canonical invoice record for this vendor.",
        })

    if po is None:
        findings.append({
            "type": "MISSING_PO",
            "details": f"No canonical purchase order file was found for PO '{po_id}'.",
        })
        po_items: list[dict[str, Any]] = []
    else:
        po_items = _po_items(po)
        findings.extend(_vendor_findings(invoice, po))
        if str(po.get("status") or "").upper() == "CANCELLED":
            findings.append({
                "type": "PO_CANCELLED",
                "details": f"Purchase order '{po.get('po_number') or po_id}' is cancelled.",
            })
        if not po_items:
            findings.append({
                "type": "PO_ITEMS_MISSING",
                "details": "The purchase order has no line items available for item-level matching.",
            })

    invoice_items = _invoice_items(invoice)
    if not invoice_items:
        findings.append({
            "type": "INVOICE_ITEMS_MISSING",
            "details": "The canonical invoice has no line items; item-level quantity and price matching cannot be completed.",
        })

    invoice_qty_by_po_index: dict[int, float] = defaultdict(float)
    invoice_rows_by_po_index: dict[int, list[dict[str, Any]]] = defaultdict(list)

    if po_items and invoice_items:
        for invoice_item in invoice_items:
            matched_index = _match_po_item(invoice_item, po_items)
            description = _item_description(invoice_item) or _item_sku(invoice_item) or "Unnamed invoice item"
            if matched_index is None:
                findings.append({
                    "type": "UNKNOWN_OR_AMBIGUOUS_ITEM",
                    "details": f"Invoice item '{description}' could not be matched uniquely to a PO line by SKU or exact description.",
                })
                continue

            invoice_quantity = _item_quantity(invoice_item, "invoice")
            if invoice_quantity is None:
                findings.append({
                    "type": "INVOICE_QUANTITY_MISSING",
                    "details": f"Invoice item '{description}' has no valid quantity.",
                })
            else:
                invoice_qty_by_po_index[matched_index] += invoice_quantity

            invoice_price = _item_unit_price(invoice_item, "invoice")
            po_price = _item_unit_price(po_items[matched_index], "po")
            if invoice_price is not None and po_price is not None:
                tolerance = _number(po.get("price_tolerance_percent")) if po else None
                tolerance = max(tolerance or 0.0, 0.0)
                allowed_price = po_price * (1.0 + tolerance / 100.0)
                if invoice_price > allowed_price + 0.0001:
                    findings.append({
                        "type": "UNIT_PRICE_EXCEEDED",
                        "details": (
                            f"Invoice unit price ({invoice_price:.4f}) for '{description}' exceeds "
                            f"the PO approved unit price ({po_price:.4f}) plus {tolerance:g}% tolerance."
                        ),
                    })
            elif invoice_price is None or po_price is None:
                findings.append({
                    "type": "UNIT_PRICE_NOT_VERIFIABLE",
                    "details": f"A valid unit price is missing for invoice item '{description}' or its PO line.",
                })

            invoice_rows_by_po_index[matched_index].append(invoice_item)

        for po_index, invoiced_quantity in invoice_qty_by_po_index.items():
            po_item = po_items[po_index]
            description = _item_description(po_item) or f"PO line {po_index + 1}"
            ordered_quantity = _item_quantity(po_item, "po")
            if ordered_quantity is None:
                findings.append({
                    "type": "PO_QUANTITY_MISSING",
                    "details": f"PO item '{description}' has no valid ordered quantity.",
                })
            elif invoiced_quantity > ordered_quantity + 0.0001:
                findings.append({
                    "type": "INVOICE_EXCEEDS_PO_QUANTITY",
                    "details": f"Invoiced quantity ({invoiced_quantity:g}) for '{description}' exceeds ordered quantity ({ordered_quantity:g}).",
                })

    if grn is None:
        findings.append({
            "type": "MISSING_GRN",
            "details": f"No canonical goods receipt file was found for PO '{po_id}'.",
        })
    else:
        grn_status = str(grn.get("status") or grn.get("receipt_status") or "UNKNOWN").upper()
        if grn_status in {"CANCELLED", "VOID"}:
            findings.append({
                "type": "GRN_CANCELLED",
                "details": f"The goods receipt status is '{grn_status}'.",
            })

        grn_items = _grn_items(grn)
        if not grn_items:
            findings.append({
                "type": "GRN_ITEMS_MISSING",
                "details": "The goods receipt has no item-level quantities; accepted quantities cannot be verified.",
            })
        elif po_items and invoice_items:
            accepted_by_po_index: dict[int, float] = defaultdict(float)
            accepted_known_by_po_index: dict[int, bool] = defaultdict(lambda: True)
            received_by_po_index: dict[int, float] = defaultdict(float)
            rejected_by_po_index: dict[int, float] = defaultdict(float)

            for grn_item in grn_items:
                matched_index = _match_po_item(grn_item, po_items)
                if matched_index is None:
                    continue
                accepted = _item_quantity(grn_item, "grn_accepted")
                received = _item_quantity(grn_item, "grn_received")
                rejected = _item_quantity(grn_item, "grn_rejected")
                if accepted is None:
                    accepted_known_by_po_index[matched_index] = False
                else:
                    accepted_by_po_index[matched_index] += accepted
                if received is not None:
                    received_by_po_index[matched_index] += received
                if rejected is not None:
                    rejected_by_po_index[matched_index] += rejected

            for po_index, invoiced_quantity in invoice_qty_by_po_index.items():
                if not accepted_known_by_po_index[po_index]:
                    description = _item_description(po_items[po_index]) or f"PO line {po_index + 1}"
                    findings.append({
                        "type": "GRN_ACCEPTED_QUANTITY_MISSING",
                        "details": f"The GRN does not record a valid accepted quantity for '{description}'.",
                    })
                    continue

                accepted_quantity = accepted_by_po_index[po_index]
                description = _item_description(po_items[po_index]) or f"PO line {po_index + 1}"
                if invoiced_quantity > accepted_quantity + 0.0001:
                    findings.append({
                        "type": "INVOICE_EXCEEDS_ACCEPTED_GRN_QUANTITY",
                        "details": (
                            f"Invoiced quantity ({invoiced_quantity:g}) for '{description}' exceeds "
                            f"the total accepted quantity in the GRN ({accepted_quantity:g})."
                        ),
                    })
                if rejected_by_po_index[po_index] > 0:
                    findings.append({
                        "type": "GRN_HAS_REJECTED_QUANTITY",
                        "details": (
                            f"The GRN records {rejected_by_po_index[po_index]:g} rejected unit(s) for "
                            f"'{description}'. Confirm the invoice excludes rejected goods."
                        ),
                    })

        pending_inspection = _number(grn.get("total_pending_inspection"))
        if pending_inspection is not None and pending_inspection > 0:
            findings.append({
                "type": "GRN_PENDING_INSPECTION",
                "details": f"The GRN still has {pending_inspection:g} unit(s) pending inspection.",
            })
        elif grn_status == "PENDING_INSPECTION":
            findings.append({
                "type": "GRN_PENDING_INSPECTION",
                "details": "The GRN status indicates that goods are pending inspection.",
            })

    # Compare header totals only when both records contain them. PO total is the
    # saved, tax-inclusive total, so the PO's configured price tolerance applies.
    if po is not None:
        invoice_total = _number(_first_value(invoice.get("total_amount"), invoice.get("total")))
        po_total = _number(_first_value(po.get("total_amount"), po.get("total")))
        if invoice_total is not None and po_total is not None:
            tolerance = _number(po.get("price_tolerance_percent")) or 0.0
            tolerance = max(tolerance, 0.0)
            allowed_total = po_total * (1.0 + tolerance / 100.0)
            if invoice_total > allowed_total + 0.0001:
                findings.append({
                    "type": "INVOICE_TOTAL_EXCEEDS_PO",
                    "details": (
                        f"Invoice total ({invoice_total:.2f}) exceeds PO total ({po_total:.2f}) "
                        f"plus {tolerance:g}% tolerance."
                    ),
                })

    # Remove exact duplicate findings while preserving their first occurrence.
    unique_findings: list[dict[str, str]] = []
    seen_findings: set[tuple[str, str]] = set()
    for finding in findings:
        key = (finding["type"], finding["details"])
        if key not in seen_findings:
            seen_findings.add(key)
            unique_findings.append(finding)

    result = "DISCREPANCIES_FOUND" if unique_findings else "NO_DISCREPANCIES_FOUND"
    return {
        "invoice_number": invoice_number,
        "po_id": po_id,
        "source_invoice_file": invoice_path.name,
        # A clean match is still only a recommendation; it is not approval.
        "status": "NEEDS_HUMAN_REVIEW",
        "matching_result": result,
        "recommendation": "FLAG_FOR_HUMAN_REVIEW" if unique_findings else "MATCHED_PENDING_HUMAN_APPROVAL",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "discrepancies": unique_findings,
    }


def save_audit_report(
    invoice_number: Any,
    report_data: dict[str, Any],
    *,
    base_dir: Path | str | None = None,
) -> Path:
    root = Path(base_dir) if base_dir is not None else BASE_DIR
    audit_dir = root / "data" / "audit_reports"
    audit_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    audit_file = audit_dir / f"audit_{_safe_filename(invoice_number)}_{timestamp}.json"
    with audit_file.open("w", encoding="utf-8") as handle:
        json.dump(report_data, handle, indent=2, ensure_ascii=False)
    return audit_file


def process_invoice_record(
    invoice_path: Path | str,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Match one newly saved canonical invoice and write its audit report.

    ``invoice_path`` should be the path returned by ``save_invoice``. Only a
    canonical ``inv_*.json`` file directly inside ``data/invoices`` is accepted;
    extraction-cache JSON files are deliberately rejected.
    """
    root = Path(base_dir) if base_dir is not None else BASE_DIR
    invoice_dir = root / "data" / "invoices"

    supplied_path = Path(invoice_path)
    if not supplied_path.is_absolute():
        # Support both paths returned relative to the project root and paths
        # already expressed relative to the current working directory.
        if not supplied_path.exists():
            supplied_path = root / supplied_path

    try:
        canonical_path = supplied_path.resolve()
        expected_dir = invoice_dir.resolve()
    except OSError as exc:
        raise ValueError(f"Could not resolve canonical invoice path: {exc}") from exc

    if (
        canonical_path.parent != expected_dir
        or not canonical_path.name.startswith("inv_")
        or canonical_path.suffix.lower() != ".json"
    ):
        raise ValueError(
            "Three-way matching accepts only canonical data/invoices/inv_<po_id>.json records."
        )

    invoice = _load_json(canonical_path)
    if invoice is None:
        raise ValueError(f"Could not load canonical invoice record: {canonical_path.name}")

    invoice_records: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(invoice_dir.glob("inv_*.json")):
        record = _load_json(path)
        if record is not None:
            invoice_records.append((path, record))

    duplicate_keys = _duplicate_invoice_keys(invoice_records)
    po_id = _first_value(
        invoice.get("po_id"),
        invoice.get("purchase_order_id"),
        invoice.get("po_number"),
    )
    key = _po_key(po_id)
    po_dir = root / "data" / "purchase_orders"
    grn_dir = root / "data" / "goods_receipts"
    po_path = po_dir / f"po_{key}.json" if key else None
    grn_path = grn_dir / f"grn_{key}.json" if key else None

    po = _load_json(po_path) if po_path is not None and po_path.is_file() else None
    grn = _load_json(grn_path) if grn_path is not None and grn_path.is_file() else None

    report = _build_report(canonical_path, invoice, po, grn, duplicate_keys)
    audit_path = save_audit_report(
        report.get("invoice_number") or canonical_path.stem,
        report,
        base_dir=root,
    )

    result = dict(report)
    result["audit_report_path"] = str(audit_path)
    print(
        f"📄 {result.get('invoice_number') or canonical_path.name}: "
        f"{result['matching_result']} — {result['status']}"
    )
    for finding in result["discrepancies"]:
        print(f"   - {finding['type']}: {finding['details']}")
    print(f"📋 Audit saved: {audit_path.relative_to(root)}")
    return result


def process_orders_sequentially(base_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """Run matching for canonical invoices only and write one report per invoice."""
    root = Path(base_dir) if base_dir is not None else BASE_DIR
    po_dir = root / "data" / "purchase_orders"
    grn_dir = root / "data" / "goods_receipts"
    invoice_dir = root / "data" / "invoices"

    print("📂 Starting canonical JSON three-way matching...\n")
    if not invoice_dir.is_dir():
        print(f"⚠️ Invoice directory does not exist: {invoice_dir}")
        return []

    # IMPORTANT: only inv_<po_id>.json are canonical records. Extraction caches
    # such as upload_<hash>.pdf.json and invoice5.pdf.json are intentionally ignored.
    invoice_paths = sorted(invoice_dir.glob("inv_*.json"))
    if not invoice_paths:
        print("⚠️ No canonical invoice files (inv_*.json) were found.")
        return []

    invoice_records: list[tuple[Path, dict[str, Any]]] = []
    for invoice_path in invoice_paths:
        invoice = _load_json(invoice_path)
        if invoice is not None:
            invoice_records.append((invoice_path, invoice))

    duplicate_keys = _duplicate_invoice_keys(invoice_records)
    reports: list[dict[str, Any]] = []

    for invoice_path, invoice in invoice_records:
        po_id = _first_value(invoice.get("po_id"), invoice.get("purchase_order_id"), invoice.get("po_number"))
        key = _po_key(po_id)
        if not key:
            po_path = None
            grn_path = None
        else:
            po_path = po_dir / f"po_{key}.json"
            grn_path = grn_dir / f"grn_{key}.json"

        po = _load_json(po_path) if po_path is not None and po_path.is_file() else None
        grn = _load_json(grn_path) if grn_path is not None and grn_path.is_file() else None

        report = _build_report(invoice_path, invoice, po, grn, duplicate_keys)
        audit_path = save_audit_report(report.get("invoice_number") or invoice_path.stem, report, base_dir=root)
        reports.append(report)

        print(
            f"📄 {report.get('invoice_number') or invoice_path.name}: "
            f"{report['matching_result']} — {report['status']}"
        )
        if report["discrepancies"]:
            for finding in report["discrepancies"]:
                print(f"   - {finding['type']}: {finding['details']}")
        print(f"📋 Audit saved: {audit_path.relative_to(root)}\n")

    return reports


if __name__ == "__main__":
    process_orders_sequentially()
