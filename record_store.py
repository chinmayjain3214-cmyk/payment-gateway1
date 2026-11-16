
"""File-backed procurement records using PO-based naming.

Canonical files:
    data/purchase_orders/po_<po_id>.json
    data/invoices/inv_<po_id>.json
    data/goods_receipts/grn_<po_id>.json

The uploaded invoice PDF/image remains separately stored under its
content-derived filename in invoices/.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent

PREFIXES = {
    "po": "po",
    "invoice": "inv",
    "grn": "grn",
}

SUBDIRECTORIES = {
    "po": "purchase_orders",
    "invoice": "invoices",
    "grn": "goods_receipts",
}


class RecordStoreError(Exception):
    """Base exception for record storage errors."""


class RecordConflictError(RecordStoreError):
    """Raised rather than silently replacing a different record."""


class InvalidPOIdError(RecordStoreError, ValueError):
    """Raised when a PO ID cannot be resolved safely."""


def normalize_po_id(value: Any) -> int:
    """Convert an integer or PO-123 style value into a positive integer."""

    if isinstance(value, bool):
        raise InvalidPOIdError("Boolean values are not valid PO IDs.")

    if isinstance(value, int):
        po_id = value
    else:
        text = str(value or "").strip()
        match = re.fullmatch(
            r"(?:PO[-_ ]?)?(\d+)",
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            raise InvalidPOIdError(
                "PO ID must be numeric or use the PO-123 format; got "
                + repr(value)
            )

        po_id = int(match.group(1))

    if po_id <= 0:
        raise InvalidPOIdError("PO ID must be greater than zero.")

    return po_id


def record_path(
    record_type: str,
    po_id: Any,
    *,
    base_dir: Path | None = None,
) -> Path:
    """Return the canonical JSON path for a PO, invoice, or GRN."""

    if record_type not in PREFIXES:
        raise ValueError(
            "record_type must be 'po', 'invoice', or 'grn'."
        )

    root = Path(base_dir) if base_dir is not None else BASE_DIR

    directory = (
        root
        / "data"
        / SUBDIRECTORIES[record_type]
    )

    resolved_id = normalize_po_id(po_id)

    return directory / (
        f"{PREFIXES[record_type]}_{resolved_id}.json"
    )


def _json_safe(record: dict[str, Any]) -> dict[str, Any]:
    """Validate that a record can be safely represented as JSON."""

    if not isinstance(record, dict):
        raise TypeError("record must be a dictionary.")

    try:
        return json.loads(
            json.dumps(
                record,
                ensure_ascii=False,
                default=str,
            )
        )
    except (TypeError, ValueError) as exc:
        raise RecordStoreError(
            "Record is not JSON serializable."
        ) from exc


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON object, returning None if the file does not exist."""

    if not path.exists():
        return None

    try:
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RecordStoreError(
            f"Could not read existing record {path.name}: {exc}"
        ) from exc

    if not isinstance(value, dict):
        raise RecordStoreError(
            f"Existing record {path.name} is not a JSON object."
        )

    return value


def _atomic_write(
    path: Path,
    record: dict[str, Any],
    *,
    replace: bool,
) -> Path:
    """Write JSON atomically so incomplete files are not left behind."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = (
        json.dumps(
            record,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    fd, temporary_name = tempfile.mkstemp(
        prefix=path.stem + "_",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )

    temporary_path = Path(temporary_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        if not replace and path.exists():
            raise RecordConflictError(
                f"{path.name} already exists. "
                "Refusing to overwrite an existing record."
            )

        os.replace(temporary_path, path)

        return path

    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _save_po_child(
    record_type: str,
    po_id: Any,
    record: dict[str, Any],
    *,
    identity_fields: tuple[str, ...],
    base_dir: Path | None = None,
) -> Path:
    """Save one invoice or GRN using its associated PO ID."""

    resolved_id = normalize_po_id(po_id)

    path = record_path(
        record_type,
        resolved_id,
        base_dir=base_dir,
    )

    payload = _json_safe(record)

    payload["po_id"] = resolved_id
    payload["record_id"] = (
        f"{PREFIXES[record_type]}_{resolved_id}"
    )

    existing = _read_json(path)

    if existing is not None:
        identity_pairs = [
            (existing.get(field), payload.get(field))
            for field in identity_fields
            if (
                existing.get(field) is not None
                or payload.get(field) is not None
            )
        ]

        same_identity = (
            bool(identity_pairs)
            and all(
                old_value == new_value
                for old_value, new_value in identity_pairs
            )
        )

        if same_identity:
            if existing == payload:
                return path

            raise RecordConflictError(
                f"{path.name} already exists for this {record_type}, "
                "but its contents differ. Review the existing record "
                "before changing it."
            )

        raise RecordConflictError(
            f"{path.name} already contains a different {record_type} "
            "for this PO. No data was overwritten. The team must "
            "define how multiple records for one PO should be named."
        )

    return _atomic_write(
        path,
        payload,
        replace=False,
    )


def save_purchase_order(
    po_id: Any,
    record: dict[str, Any],
    *,
    base_dir: Path | None = None,
) -> Path:
    """Save a PO as data/purchase_orders/po_<po_id>.json."""

    resolved_id = normalize_po_id(po_id)

    path = record_path(
        "po",
        resolved_id,
        base_dir=base_dir,
    )

    payload = _json_safe(record)

    payload["po_id"] = resolved_id
    payload["record_id"] = f"po_{resolved_id}"

    existing = _read_json(path)

    if existing is not None:
        old_po_number = existing.get("po_number")
        new_po_number = payload.get("po_number")

        if (
            old_po_number
            and new_po_number
            and old_po_number != new_po_number
        ):
            raise RecordConflictError(
                f"{path.name} is already assigned to PO "
                f"{old_po_number}; it cannot be reassigned to "
                f"{new_po_number}."
            )

    return _atomic_write(
        path,
        payload,
        replace=True,
    )


def save_invoice(
    po_id: Any,
    record: dict[str, Any],
    *,
    base_dir: Path | None = None,
) -> Path:
    """Save an invoice as data/invoices/inv_<po_id>.json."""

    return _save_po_child(
        "invoice",
        po_id,
        record,
        identity_fields=(
            "invoice_number",
            "vendor_id",
        ),
        base_dir=base_dir,
    )


def save_goods_receipt(
    po_id: Any,
    record: dict[str, Any],
    *,
    base_dir: Path | None = None,
) -> Path:
    """Save a GRN as data/goods_receipts/grn_<po_id>.json."""

    return _save_po_child(
        "grn",
        po_id,
        record,
        identity_fields=(
            "grn_number",
            "delivery_reference",
        ),
        base_dir=base_dir,
    )


def load_record(
    record_type: str,
    po_id: Any,
    *,
    base_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Load a canonical PO, invoice, or GRN JSON record."""

    return _read_json(
        record_path(
            record_type,
            po_id,
            base_dir=base_dir,
        )
    )
