"""Exact purchase-order lookup across reference data and saved PO JSON records."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rules import load_reference_data

BASE_DIR = Path(__file__).resolve().parent
PURCHASE_ORDER_DIR = BASE_DIR / "data" / "purchase_orders"
GOODS_RECEIPT_DIR = BASE_DIR / "data" / "goods_receipts"


def normalize(po_number: Any) -> str:
    """Normalize PO references for exact comparison without punctuation."""
    return re.sub(r"[^a-z0-9]", "", str(po_number or "").lower())


def _load_json_records(directory: Path, prefix: str) -> list[dict[str, Any]]:
    """Load canonical JSON records, failing clearly on corrupt saved files."""
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise ValueError(f"Record storage path is not a directory: {directory}")

    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob(f"{prefix}_*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read saved record {path.name}: {exc}") from exc

        if not isinstance(record, dict):
            raise ValueError(f"Saved record {path.name} must contain a JSON object.")
        records.append(record)

    return records


def load_saved_purchase_orders() -> list[dict[str, Any]]:
    """Return PO records stored under data/purchase_orders/po_<id>.json."""
    records = _load_json_records(PURCHASE_ORDER_DIR, "po")
    for record in records:
        if not str(record.get("po_number") or "").strip():
            raise ValueError("A saved purchase order is missing its po_number.")
    return records


def load_saved_goods_receipts() -> list[dict[str, Any]]:
    """Return GRN records stored under data/goods_receipts/grn_<id>.json."""
    records = _load_json_records(GOODS_RECEIPT_DIR, "grn")
    for record in records:
        if not str(record.get("po_number") or "").strip():
            raise ValueError("A saved goods receipt is missing its po_number.")
    return records


def _prepare_po(record: dict[str, Any]) -> dict[str, Any]:
    """Return a PO shape compatible with the existing vendor checks."""
    po = dict(record)
    vendor = po.get("vendor_name") or po.get("vendor")
    if isinstance(vendor, dict):
        vendor = (
            vendor.get("name")
            or vendor.get("vendor_name")
            or vendor.get("supplier_name")
        )
    po["vendor"] = vendor
    if vendor and not po.get("vendor_name"):
        po["vendor_name"] = vendor
    return po


def _find_exact(records: list[dict[str, Any]], wanted: str) -> list[dict[str, Any]]:
    return [
        record for record in records
        if normalize(record.get("po_number")) == wanted
    ]


def find_po(po_number: str) -> dict[str, Any]:
    """Find an exact PO match; never guess or accept a partial match.

    Saved PO JSON records take precedence over the static reference fixtures,
    allowing the agent to recognize purchase orders created in the app.
    """
    wanted = normalize(po_number)
    if not wanted:
        return {
            "status": "not_found",
            "po": None,
            "note": "No PO reference was supplied.",
        }

    saved_matches = _find_exact(load_saved_purchase_orders(), wanted)
    if len(saved_matches) > 1:
        return {
            "status": "ambiguous",
            "po": None,
            "note": f"More than one saved purchase order matches '{po_number}'. Manual confirmation is required.",
        }
    if saved_matches:
        return {
            "status": "found",
            "po": _prepare_po(saved_matches[0]),
            "note": "Exact match in saved purchase-order records.",
        }

    reference = load_reference_data()
    reference_pos = reference.get("purchase_orders", [])
    if not isinstance(reference_pos, list):
        reference_pos = []
    reference_pos = [record for record in reference_pos if isinstance(record, dict)]
    reference_matches = _find_exact(reference_pos, wanted)

    if len(reference_matches) > 1:
        return {
            "status": "ambiguous",
            "po": None,
            "note": f"More than one reference purchase order matches '{po_number}'. Manual confirmation is required.",
        }
    if reference_matches:
        return {
            "status": "found",
            "po": _prepare_po(reference_matches[0]),
            "note": "Exact match in procurement reference data.",
        }

    return {
        "status": "not_found",
        "po": None,
        "note": (
            "No PO matching '" + str(po_number)
            + "' exists in saved purchase orders or procurement reference data."
        ),
    }


if __name__ == "__main__":
    print(find_po("PO-101"))
    print(find_po("PO-2026-99A"))
