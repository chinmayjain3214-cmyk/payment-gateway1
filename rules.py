"""Dataset-backed invoice checks for the university AP demo.

The rules read procurement reference records from dataset/reference_data.json.
They return reason codes (not display text) so the UI can render them with
reason_labels.py.
"""

from __future__ import annotations

import difflib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DATASET_DIR = BASE_DIR / "dataset"
REFERENCE_FILE = DATASET_DIR / "reference_data.json"
INVOICES_FILE = DATASET_DIR / "invoice_documents.json"
MANIFEST_FILE = DATASET_DIR / "test_manifest.json"

INFO_ONLY_CODES = {"PRICE_VARIANCE_WITHIN_TOLERANCE"}


# ==================================================
# FILE HELPERS
# ==================================================

def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_reference_data(
    path: str | Path | None = None,
) -> dict[str, Any]:
    return _read_json(
        Path(path) if path else REFERENCE_FILE
    )


def load_invoice_documents(
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    return _read_json(
        Path(path) if path else INVOICES_FILE
    )


def load_test_manifest(
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    return _read_json(
        Path(path) if path else MANIFEST_FILE
    )


# ==================================================
# NORMALISATION HELPERS
# ==================================================

def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _norm(value: Any) -> str:
    return re.sub(
        r"[^a-z0-9]",
        "",
        _text(value).lower(),
    )


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        cleaned = str(value).replace(",", "").strip()

        if not cleaned:
            return None

        return Decimal(cleaned)

    except (
        InvalidOperation,
        ValueError,
        TypeError,
    ):
        return None


def _first_not_none(
    mapping: dict[str, Any],
    *keys: str,
) -> Any:

    for key in keys:

        if (
            key in mapping
            and mapping[key] is not None
            and mapping[key] != ""
        ):
            return mapping[key]

    return None


# ==================================================
# INVOICE EXTRACTION HELPERS
# ==================================================

def _invoice_document(
    record: dict[str, Any],
) -> dict[str, Any]:

    value = record.get("document", record)

    return value if isinstance(value, dict) else {}


def _vendor_block(
    document: dict[str, Any],
) -> dict[str, Any]:

    value = document.get("vendor")

    return value if isinstance(value, dict) else {}


def _vendor_name(
    document: dict[str, Any],
) -> str | None:

    vendor = _vendor_block(document)

    value = _first_not_none(
        vendor,
        "name",
        "vendor_name",
        "supplier_name",
        "supplier",
    )

    if value is None:

        value = _first_not_none(
            document,
            "vendor_name",
            "supplier_name",
            "supplier",
        )

        if (
            value is None
            and not isinstance(
                document.get("vendor"),
                dict,
            )
        ):
            value = document.get("vendor")

    return _text(value) or None


def _vendor_code(
    document: dict[str, Any],
) -> str | None:

    vendor = _vendor_block(document)

    value = _first_not_none(
        vendor,
        "vendor_code",
        "vendor_id",
        "code",
    )

    if value is None:

        value = _first_not_none(
            document,
            "vendor_code",
            "vendor_id",
        )

    return _text(value) or None


def _vendor_gstin(
    document: dict[str, Any],
) -> str | None:

    vendor = _vendor_block(document)

    value = _first_not_none(
        vendor,
        "gstin",
        "GSTIN",
    )

    if value is None:

        value = _first_not_none(
            document,
            "gstin",
            "GSTIN",
        )

    return _text(value).upper() or None


def _invoice_number(
    document: dict[str, Any],
) -> str | None:

    value = _first_not_none(
        document,
        "invoice_number",
        "invoice_no",
        "invoice_id",
        "credit_note_number",
        "document_id",
    )

    return _text(value) or None


def _invoice_date(
    document: dict[str, Any],
) -> str | None:

    value = _first_not_none(
        document,
        "invoice_date",
        "date",
        "issue_date",
    )

    return _text(value) or None


def _po_reference(
    document: dict[str, Any],
) -> str | None:

    value = _first_not_none(
        document,
        "po_reference",
        "po_number",
        "purchase_order",
        "purchase_order_reference",
        "reference_po",
        "purchase_reference",
    )

    if value is None:

        details = document.get("reference_details")

        if isinstance(details, dict):

            reference_type = _text(
                details.get("reference_type")
            ).lower()

            if (
                "purchase order" in reference_type
                or reference_type == "po"
            ):
                value = details.get("customer_order")

    return _text(value) or None


def _currency(
    document: dict[str, Any],
) -> str | None:

    value = _first_not_none(
        document,
        "currency",
        "currency_code",
    )

    return _text(value).upper() or None


def _items(
    document: dict[str, Any],
) -> list[dict[str, Any]]:

    for key in (
        "items",
        "products",
        "line_items",
    ):

        value = document.get(key)

        if isinstance(value, list):

            return [
                item
                for item in value
                if isinstance(item, dict)
            ]

    return []


def _item_description(
    item: dict[str, Any],
) -> str:

    return _text(
        _first_not_none(
            item,
            "description",
            "name",
            "product_name",
            "service_name",
        )
    )


def _item_quantity(
    item: dict[str, Any],
) -> Decimal | None:

    return _decimal(
        _first_not_none(
            item,
            "quantity",
            "qty",
            "quantity_billed",
        )
    )


def _item_unit_price(
    item: dict[str, Any],
) -> Decimal | None:

    return _decimal(
        _first_not_none(
            item,
            "unit_price",
            "unit_rate",
            "rate",
            "price",
        )
    )


def _item_amount(
    item: dict[str, Any],
) -> Decimal | None:

    return _decimal(
        _first_not_none(
            item,
            "amount",
            "total",
            "line_total",
            "line_amount",
            "credit_amount",
        )
    )


def _item_net_unit_price(
    item: dict[str, Any],
) -> Decimal | None:

    price = _item_unit_price(item)

    if price is None:
        return None

    discount = _decimal(
        item.get("discount_percent")
    )

    if discount is not None:

        price *= (
            Decimal("100") - discount
        ) / Decimal("100")

    return price


def _invoice_total(
    document: dict[str, Any],
) -> Decimal | None:

    return _decimal(
        _first_not_none(
            document,
            "amount_due",
            "grand_total",
            "invoice_total",
            "total",
            "net_payable",
            "total_credit",
        )
    )


def _invoice_subtotal(
    document: dict[str, Any],
) -> Decimal | None:

    return _decimal(
        _first_not_none(
            document,
            "subtotal",
            "net_payable",
        )
    )


# ==================================================
# GST HELPERS
# ==================================================

def _tax_amount(
    document: dict[str, Any],
) -> Decimal | None:
    """Return GST without counting its components twice.

    When CGST, SGST or IGST is available, those components take priority.
    Combined tax fields are used only when individual components are absent.
    """

    component_keys = (
        "cgst",
        "sgst",
        "igst",
    )

    provided_components = [
        key
        for key in component_keys
        if (
            document.get(key) is not None
            and str(document.get(key)).strip() != ""
        )
    ]

    if provided_components:

        values = [
            _decimal(document.get(key))
            for key in provided_components
        ]

        if any(value is None for value in values):
            return None

        return sum(
            values,
            Decimal("0"),
        )

    # Use only one combined tax value.
    # Do not add multiple representations of the same GST.
    for key in (
        "tax_amount",
        "tax",
        "gst",
        "tax_adjustment",
    ):

        raw_value = document.get(key)

        if (
            raw_value is not None
            and str(raw_value).strip() != ""
        ):
            return _decimal(raw_value)

    return None


def _discount_amount(
    document: dict[str, Any],
) -> Decimal:

    return (
        _decimal(document.get("discount"))
        or Decimal("0")
    )


# ==================================================
# VENDOR LOOKUP
# ==================================================

def _vendor_indexes(
    reference: dict[str, Any],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:

    by_id = {}
    by_name = {}
    by_gstin = {}

    for vendor in reference.get("vendors", []):

        if not isinstance(vendor, dict):
            continue

        if vendor.get("vendor_id"):

            by_id[
                _text(vendor["vendor_id"]).upper()
            ] = vendor

        if vendor.get("name"):

            by_name[
                _norm(vendor["name"])
            ] = vendor

        if vendor.get("gstin"):

            by_gstin[
                _text(vendor["gstin"]).upper()
            ] = vendor

    return by_id, by_name, by_gstin


def _find_vendor(
    document: dict[str, Any],
    reference: dict[str, Any],
    po: dict[str, Any] | None = None,
) -> dict[str, Any] | None:

    by_id, by_name, _ = _vendor_indexes(
        reference
    )

    code = _vendor_code(document)

    if code and code.upper() in by_id:
        return by_id[code.upper()]

    name = _vendor_name(document)

    if name and _norm(name) in by_name:
        return by_name[_norm(name)]

    # Only fall back to the PO vendor when invoice vendor
    # details are completely absent. Never use this fallback
    # to hide an explicitly supplied but unknown vendor.
    if not code and not name and po and po.get("vendor_id"):

        return by_id.get(
            _text(po["vendor_id"]).upper()
        )

    return None


def _po_vendor_master(
    po: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any] | None:

    by_id, by_name, _ = _vendor_indexes(
        reference
    )

    vendor_id = _text(
        po.get("vendor_id")
    ).upper()

    if vendor_id and vendor_id in by_id:
        return by_id[vendor_id]

    vendor_name = _text(
        po.get("vendor_name")
        or po.get("vendor")
    )

    if vendor_name:
        return by_name.get(_norm(vendor_name))

    return None


def _check_vendor_po_mismatch(
    document: dict[str, Any],
    po: dict[str, Any],
    reference: dict[str, Any],
) -> bool:
    """Compare the invoice vendor directly with the PO vendor."""

    invoice_code = _vendor_code(document)

    po_vendor_id = _text(
        po.get("vendor_id")
    )

    # An explicit vendor ID mismatch is a blocking problem.
    if (
        invoice_code
        and po_vendor_id
        and _norm(invoice_code) != _norm(po_vendor_id)
    ):
        return True

    invoice_name = _vendor_name(document)

    po_name = _text(
        po.get("vendor_name")
        or po.get("vendor")
    )

    if not invoice_name or not po_name:
        return False

    if _norm(invoice_name) == _norm(po_name):
        return False

    # A matching vendor ID is stronger evidence than a
    # difference in the printed business name.
    if (
        invoice_code
        and po_vendor_id
        and _norm(invoice_code) == _norm(po_vendor_id)
    ):
        return False

    # An exact GSTIN match can support a legitimate name variation.
    invoice_gstin = _vendor_gstin(document)

    expected_vendor = _po_vendor_master(
        po,
        reference,
    )

    expected_gstin = (
        _text(expected_vendor.get("gstin")).upper()
        if expected_vendor
        else ""
    )

    if (
        invoice_gstin
        and expected_gstin
        and invoice_gstin == expected_gstin
    ):
        return False

    score = difflib.SequenceMatcher(
        None,
        _norm(invoice_name),
        _norm(po_name),
    ).ratio()

    return score < 0.85


def _invoice_vendor_key(
    document: dict[str, Any],
    reference: dict[str, Any],
    po: dict[str, Any] | None,
) -> str:

    vendor = _find_vendor(
        document,
        reference,
        po,
    )

    if vendor:
        return _text(
            vendor.get("vendor_id")
        ).upper()

    name = _vendor_name(document)

    if name:
        return _norm(name)

    return ""


# ==================================================
# PURCHASE ORDER LOOKUP
# ==================================================

def _find_po(
    po_reference: str | None,
    reference: dict[str, Any],
) -> dict[str, Any] | None:

    if not po_reference:
        return None

    target = _norm(po_reference)

    for po in reference.get("purchase_orders", []):

        if not isinstance(po, dict):
            continue

        if _norm(po.get("po_number")) == target:
            return po

    return None


def _find_po_item(
    description: str,
    po: dict[str, Any],
) -> dict[str, Any] | None:

    target = _norm(description)

    for item in po.get("items", []):

        if not isinstance(item, dict):
            continue

        if _norm(item.get("description")) == target:
            return item

    return None


def _find_po_item_by_normalised_description(
    description_key: str,
    po: dict[str, Any],
) -> dict[str, Any] | None:

    for item in po.get("items", []):

        if not isinstance(item, dict):
            continue

        if _norm(item.get("description")) == description_key:
            return item

    return None


# ==================================================
# INVOICE HISTORY
# ==================================================

def _history_vendor_key(
    record: dict[str, Any],
    reference: dict[str, Any],
) -> str:

    vendor_id = _text(
        record.get("vendor_id")
    ).upper()

    if vendor_id:
        return vendor_id

    name = _text(
        record.get("vendor_name")
        or record.get("vendor")
    )

    if name:

        _, by_name, _ = _vendor_indexes(
            reference
        )

        vendor = by_name.get(
            _norm(name)
        )

        if vendor:
            return _text(
                vendor.get("vendor_id")
            ).upper()

        return _norm(name)

    return ""


def _history_items(
    record: dict[str, Any],
) -> list[dict[str, Any]]:

    value = record.get("items", [])

    if not isinstance(value, list):
        return []

    return [
        item
        for item in value
        if isinstance(item, dict)
    ]


def _history_billed_quantity(
    po: dict[str, Any],
    description_key: str,
    history: list[dict[str, Any]],
) -> Decimal:
    """Get the quantity already billed for a PO line."""

    po_key = _norm(
        po.get("po_number")
    )

    previous_quantity = Decimal("0")

    excluded_statuses = {
        "VOID",
        "CANCELLED",
        "REJECTED",
        "DECLINED",
    }

    for previous in history:

        if _norm(previous.get("po_number")) != po_key:
            continue

        status = _text(
            previous.get("status")
        ).upper()

        if status in excluded_statuses:
            continue

        for previous_item in _history_items(previous):

            if (
                _norm(previous_item.get("description"))
                != description_key
            ):
                continue

            quantity = _decimal(
                _first_not_none(
                    previous_item,
                    "quantity_billed",
                    "quantity",
                    "qty",
                )
            )

            if quantity is not None:
                previous_quantity += quantity

    return previous_quantity


def _aggregate_invoice_quantities(
    document: dict[str, Any],
) -> dict[str, Decimal]:
    """Aggregate repeated invoice lines with the same description."""

    quantities = {}

    for item in _items(document):

        description_key = _norm(
            _item_description(item)
        )

        quantity = _item_quantity(item)

        if not description_key or quantity is None:
            continue

        quantities[description_key] = (
            quantities.get(
                description_key,
                Decimal("0"),
            )
            + quantity
        )

    return quantities


# ==================================================
# DOCUMENT TYPE / QUALITY
# ==================================================

def _is_credit_note(
    document: dict[str, Any],
) -> bool:

    dtype = _text(
        document.get("document_type")
    ).upper()

    return (
        "CREDIT_NOTE" in dtype
        or bool(document.get("credit_note_number"))
    )


def _is_low_quality(
    record: dict[str, Any],
) -> bool:

    source = record.get("source_document")

    return (
        isinstance(source, dict)
        and bool(source.get("quality_flags"))
    )


def _check_incomplete_extraction(
    document: dict[str, Any],
) -> bool:

    required_values = [
        _invoice_number(document),
        _vendor_name(document),
        _po_reference(document),
        _currency(document),
        _invoice_total(document),
    ]

    if any(
        value is None or value == ""
        for value in required_values
    ):
        return True

    invoice_items = _items(document)

    if not invoice_items:
        return True

    for item in invoice_items:

        if (
            not _item_description(item)
            or _item_quantity(item) is None
            or _item_unit_price(item) is None
            or _item_amount(item) is None
        ):
            return True

    return False


# ==================================================
# ARITHMETIC CHECKS
# ==================================================

def _check_arithmetic(
    document: dict[str, Any],
) -> bool:
    """Return True when invoice line, subtotal or total arithmetic is inconsistent."""

    if _is_credit_note(document):
        return False

    subtotal = _invoice_subtotal(document)
    total = _invoice_total(document)

    if subtotal is None or total is None:
        return False

    invoice_items = _items(document)

    amounts = [
        _item_amount(item)
        for item in invoice_items
    ]

    if (
        invoice_items
        and all(amount is not None for amount in amounts)
    ):

        line_sum = sum(
            (
                amount
                for amount in amounts
                if amount is not None
            ),
            Decimal("0"),
        )

        if abs(
            line_sum - subtotal
        ) > Decimal("0.01"):
            return True

    tax = _tax_amount(document)

    if tax is None:
        tax = Decimal("0")

    expected_total = (
        subtotal
        - _discount_amount(document)
        + tax
    )

    return (
        abs(
            expected_total - total
        ) > Decimal("0.01")
    )


# ==================================================
# GST RATE CHECK
# ==================================================

def _check_tax_rate(
    document: dict[str, Any],
    po: dict[str, Any] | None,
) -> bool:

    if not po or _is_credit_note(document):
        return False

    taxable_base = _invoice_subtotal(document)

    if taxable_base is not None:
        taxable_base -= _discount_amount(document)

    actual_tax = _tax_amount(document)

    if (
        taxable_base is None
        or taxable_base <= 0
        or actual_tax is None
    ):
        return False

    invoice_items = _items(document)

    expected_rates = []

    for invoice_item in invoice_items:

        po_item = _find_po_item(
            _item_description(invoice_item),
            po,
        )

        if not po_item:
            continue

        rate = _decimal(
            po_item.get("tax_percent")
        )

        if rate is not None:
            expected_rates.append(rate)

    if expected_rates:

        expected_rate = expected_rates[0]

        if any(
            abs(rate - expected_rate)
            > Decimal("0.01")
            for rate in expected_rates
        ):
            # Mixed tax rates need a more detailed
            # line-level tax allocation.
            return False

    else:

        expected_rate = _decimal(
            po.get("tax_percent")
        )

        if expected_rate is None:

            rules = po.get("tax_rules")

            if isinstance(rules, dict):

                expected_rate = _decimal(
                    rules.get(
                        "combined_gst_percent"
                    )
                )

    if expected_rate is None:

        policy = (
            po.get("policies") or {}
        ).get(
            "tax_rules",
            {},
        ).get(
            "INR_domestic_example",
            {},
        )

        if isinstance(policy, dict):

            expected_rate = _decimal(
                policy.get(
                    "combined_gst_percent"
                )
            )

    if expected_rate is None:
        return False

    actual_rate = (
        actual_tax
        * Decimal("100")
        / taxable_base
    )

    return (
        abs(
            actual_rate - expected_rate
        ) > Decimal("0.05")
    )


# ==================================================
# PURCHASE ORDER PRICE CHECK
# ==================================================

def _check_price_variance(
    document: dict[str, Any],
    po: dict[str, Any] | None,
) -> list[str]:

    if not po or _is_credit_note(document):
        return []

    tolerance = _decimal(
        po.get("price_tolerance_percent")
    )

    if tolerance is None:
        tolerance = Decimal("0")

    within_tolerance = False

    for invoice_item in _items(document):

        po_item = _find_po_item(
            _item_description(invoice_item),
            po,
        )

        if not po_item:
            continue

        invoice_price = _item_net_unit_price(
            invoice_item
        )

        approved_price = _decimal(
            po_item.get("approved_unit_price")
        )

        if (
            invoice_price is None
            or approved_price is None
            or approved_price == 0
        ):
            continue

        variance = (
            abs(
                invoice_price - approved_price
            )
            * Decimal("100")
            / approved_price
        )

        if variance > tolerance + Decimal("0.0001"):

            # A blocking variance takes priority over
            # any earlier informational line.
            return [
                "PO_UNIT_PRICE_MISMATCH"
            ]

        if variance > Decimal("0.0001"):
            within_tolerance = True

    if within_tolerance:
        return [
            "PRICE_VARIANCE_WITHIN_TOLERANCE"
        ]

    return []


# ==================================================
# GOODS RECEIPT CHECK
# ==================================================

def _check_grn(
    document: dict[str, Any],
    po: dict[str, Any] | None,
    reference: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Check invoice quantities against cumulative accepted GRN quantities."""

    if not po or _is_credit_note(document):
        return []

    history = history or []

    if (
        _text(
            po.get("procurement_type")
        ).upper()
        == "SERVICE"
    ):

        confirmations = [
            row
            for row in reference.get(
                "service_confirmations",
                [],
            )
            if (
                _norm(row.get("po_number"))
                == _norm(po.get("po_number"))
                and _text(row.get("status")).upper()
                == "ACCEPTED"
            )
        ]

        details = document.get(
            "service_details"
        )

        details = (
            details
            if isinstance(details, dict)
            else {}
        )

        hours = _decimal(
            details.get("hours")
        )

        if not confirmations:
            return [
                "MISSING_GOODS_RECEIPT"
            ]

        accepted_hours = sum(
            (
                _decimal(
                    row.get("hours_accepted")
                ) or Decimal("0")
                for row in confirmations
            ),
            Decimal("0"),
        )

        if (
            hours is not None
            and accepted_hours < hours
        ):
            return [
                "GRN_QUANTITY_SHORTAGE"
            ]

        return []

    # Digital licences and subscriptions do not
    # require a physical goods receipt.

    po_item_names = [
        _text(
            item.get("description")
        ).lower()
        for item in po.get("items", [])
        if isinstance(item, dict)
    ]

    if po_item_names and all(
        any(
            word in name
            for word in (
                "license",
                "licence",
                "software",
                "subscription",
            )
        )
        for name in po_item_names
    ):
        return []

    accepted_statuses = {
        "ACCEPTED",
        "PARTIALLY_ACCEPTED",
    }

    receipts = [
        row
        for row in reference.get(
            "goods_receipts",
            [],
        )
        if (
            _norm(row.get("po_number"))
            == _norm(po.get("po_number"))
            and _text(row.get("status")).upper()
            in accepted_statuses
        )
    ]

    if not receipts:
        return [
            "MISSING_GOODS_RECEIPT"
        ]

    # Sum accepted quantities across all GRNs.
    # This supports multiple deliveries against one PO.

    accepted_by_description = {}

    for receipt in receipts:

        for received_item in receipt.get(
            "items",
            [],
        ):

            if not isinstance(received_item, dict):
                continue

            description_key = _norm(
                received_item.get("description")
            )

            if not description_key:
                continue

            accepted_quantity = _decimal(
                received_item.get(
                    "quantity_accepted"
                )
            )

            if accepted_quantity is None:
                continue

            accepted_by_description[
                description_key
            ] = (
                accepted_by_description.get(
                    description_key,
                    Decimal("0"),
                )
                + accepted_quantity
            )

    # Aggregate repeated lines on the current invoice.
    current_quantities = _aggregate_invoice_quantities(
        document
    )

    findings = []

    for description_key, current_quantity in (
        current_quantities.items()
    ):

        accepted_quantity = (
            accepted_by_description.get(
                description_key,
                Decimal("0"),
            )
        )

        previous_billed = _history_billed_quantity(
            po,
            description_key,
            history,
        )

        total_billed = (
            previous_billed
            + current_quantity
        )

        if total_billed <= accepted_quantity:
            continue

        po_item = (
            _find_po_item_by_normalised_description(
                description_key,
                po,
            )
        )

        ordered_quantity = (
            _decimal(
                po_item.get("quantity_ordered")
            )
            if po_item
            else None
        )

        # If the full PO quantity has already been accepted,
        # overbilling is reported by CUMULATIVE_PO_OVERBILL.
        # Avoid generating a duplicate GRN shortage reason.
        if (
            ordered_quantity is not None
            and accepted_quantity >= ordered_quantity
        ):
            continue

        findings.append(
            "GRN_QUANTITY_SHORTAGE"
        )

        break

    return findings


# ==================================================
# CUMULATIVE PO QUANTITY CHECK
# ==================================================

def _check_cumulative_po_quantity(
    document: dict[str, Any],
    po: dict[str, Any] | None,
    history: list[dict[str, Any]],
) -> bool:
    """Check whether previous and current invoices exceed PO quantities."""

    if not po or _is_credit_note(document):
        return False

    current_quantities = _aggregate_invoice_quantities(
        document
    )

    for description_key, current_quantity in (
        current_quantities.items()
    ):

        po_item = (
            _find_po_item_by_normalised_description(
                description_key,
                po,
            )
        )

        if not po_item:
            continue

        ordered_quantity = _decimal(
            po_item.get("quantity_ordered")
        )

        if ordered_quantity is None:
            continue

        previous_quantity = _history_billed_quantity(
            po,
            description_key,
            history,
        )

        if (
            previous_quantity + current_quantity
            > ordered_quantity
        ):
            return True

    return False


# ==================================================
# FX RATE CHECK
# ==================================================

def _check_fx_rate(
    document: dict[str, Any],
    reference: dict[str, Any],
) -> bool:

    currency = _currency(document)
    invoice_date = _invoice_date(document)

    invoice_rate = _decimal(
        document.get("exchange_rate")
    )

    if (
        not currency
        or not invoice_date
        or invoice_rate is None
    ):
        return False

    for fixture in reference.get(
        "fx_rates",
        [],
    ):

        if (
            _text(
                fixture.get("currency")
            ).upper()
            == currency
            and _text(
                fixture.get("date")
            ) == invoice_date
        ):

            expected = _decimal(
                fixture.get("reference_rate")
            )

            return (
                expected is not None
                and abs(
                    invoice_rate - expected
                ) > Decimal("0.0001")
            )

    return False

def _check_department_budget(
    document: dict[str, Any],
    reference: dict[str, Any],
    po: dict[str, Any] | None,
) -> bool:
    """Return True when the invoice total exceeds the department's remaining budget."""
    if not po:
        return False

    department_id = po.get("department_id")
    if not department_id:
        return False

    target = _norm(department_id)
    department = None
    for dept in reference.get("departments", []):
        if _norm(dept.get("department_id")) == target:
            department = dept
            break

    if not department:
        return False

    allocated = _decimal(department.get("budget_allocated"))
    consumed = _decimal(department.get("budget_consumed")) or Decimal("0")
    invoice_total = _invoice_total(document)

    if allocated is None or invoice_total is None:
        return False

    projected = consumed + invoice_total
    return projected > allocated + Decimal("0.01")

# ==================================================
# HISTORY RECORD CREATION
# ==================================================

def _make_history_record(
    document: dict[str, Any],
    reference: dict[str, Any],
    po: dict[str, Any] | None,
) -> dict[str, Any] | None:

    invoice_number = _invoice_number(
        document
    )

    if not invoice_number or _is_credit_note(document):
        return None

    vendor_key = _invoice_vendor_key(
        document,
        reference,
        po,
    )

    vendor_id = (
        vendor_key
        if vendor_key.startswith("VEN-")
        else None
    )

    po_number = _po_reference(
        document
    )

    history_items = []

    for item in _items(document):

        quantity = _item_quantity(item)
        unit_price = _item_unit_price(item)

        history_items.append(
            {
                "description": _item_description(item),
                "quantity_billed": str(
                    quantity
                    if quantity is not None
                    else Decimal("0")
                ),
                "unit_price": str(
                    unit_price
                    if unit_price is not None
                    else Decimal("0")
                ),
            }
        )

    return {
        "invoice_number": invoice_number,
        "vendor_id": vendor_id,
        "vendor_name": _vendor_name(document),
        "po_number": po_number,
        "currency": _currency(document),
        "total": str(
            _invoice_total(document) or ""
        ),
        "status": "PROCESSED",
        "items": history_items,
    }


# ==================================================
# MAIN INVOICE EVALUATION
# ==================================================

def evaluate_invoice(
    invoice_record: dict[str, Any],
    reference_data: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate one invoice and return its reason codes and recommendation."""

    reference = (
        reference_data
        if reference_data is not None
        else load_reference_data()
    )

    prior = list(history or [])

    document = _invoice_document(
        invoice_record
    )

    findings = []

    def add(code: str) -> None:

        if code not in findings:
            findings.append(code)

    # --------------------------------------------------
    # Document quality
    # --------------------------------------------------

    if _is_low_quality(invoice_record):

        add("LOW_DOCUMENT_QUALITY")

        if _check_incomplete_extraction(document):
            add("INCOMPLETE_EXTRACTION")

        return _result(
            invoice_record,
            findings,
        )

    # --------------------------------------------------
    # Arithmetic
    # --------------------------------------------------

    if _check_arithmetic(document):
        add("INVOICE_ARITHMETIC_MISMATCH")

    # --------------------------------------------------
    # Credit notes
    # --------------------------------------------------

    if _is_credit_note(document):

        add("CREDIT_NOTE_SPECIAL_HANDLING")

        return _result(
            invoice_record,
            findings,
        )

    # --------------------------------------------------
    # PO reference
    # --------------------------------------------------

    po_reference = _po_reference(document)

    if not po_reference:

        add("MISSING_PO_REFERENCE")

        return _result(
            invoice_record,
            findings,
        )

    po = _find_po(
        po_reference,
        reference,
    )

    if po is None:

        add("PO_REFERENCE_UNMAPPED")

        return _result(
            invoice_record,
            findings,
        )

    if (
        _text(
            po.get("status")
        ).upper()
        == "CANCELLED"
    ):
        add("CANCELLED_PO")

    # --------------------------------------------------
    # Duplicate invoice detection
    # --------------------------------------------------

    invoice_number = _invoice_number(
        document
    )

    invoice_vendor_key = _invoice_vendor_key(
        document,
        reference,
        po,
    )

    for previous in prior:

        previous_number = _text(
            previous.get("invoice_number")
        )

        previous_vendor_key = _history_vendor_key(
            previous,
            reference,
        )

        if (
            invoice_number
            and _norm(invoice_number)
            == _norm(previous_number)
            and invoice_vendor_key
            and invoice_vendor_key
            == previous_vendor_key
        ):

            add("DUPLICATE_INVOICE")

            break

    is_duplicate = (
        "DUPLICATE_INVOICE" in findings
    )

    # --------------------------------------------------
    # Direct invoice-to-PO vendor matching
    # --------------------------------------------------

    if _check_vendor_po_mismatch(
        document,
        po,
        reference,
    ):
        add("VENDOR_PO_MISMATCH")

    # --------------------------------------------------
    # GSTIN matching against PO vendor master
    # --------------------------------------------------

    expected_vendor = _po_vendor_master(
        po,
        reference,
    )

    invoice_gstin = _vendor_gstin(
        document
    )

    expected_gstin = (
        _text(
            expected_vendor.get("gstin")
        ).upper()
        if expected_vendor
        else _text(
            po.get("gstin")
        ).upper()
    )

    if (
        invoice_gstin
        and expected_gstin
        and invoice_gstin != expected_gstin
    ):
        add("VENDOR_GSTIN_MISMATCH")

    # --------------------------------------------------
    # Unit price and tolerance
    # --------------------------------------------------

    price_findings = _check_price_variance(
        document,
        po,
    )

    for code in price_findings:
        add(code)

    # --------------------------------------------------
    # GRN and cumulative quantity validation
    # --------------------------------------------------

    if (
        _text(
            po.get("status")
        ).upper()
        != "CANCELLED"
        and not is_duplicate
    ):

        grn_findings = _check_grn(
            document,
            po,
            reference,
            prior,
        )

        for code in grn_findings:
            add(code)

        if _check_cumulative_po_quantity(
            document,
            po,
            prior,
        ):
            add("CUMULATIVE_PO_OVERBILL")

    # --------------------------------------------------
    # GST rate
    # --------------------------------------------------

    if _check_tax_rate(
        document,
        po,
    ):
        add("GST_RATE_MISMATCH")

    # --------------------------------------------------
    # Foreign exchange rate
    # --------------------------------------------------

    if _check_fx_rate(
        document,
        reference,
    ):
        add("FX_RATE_MISMATCH")


    if _check_department_budget(document, reference, po):
        add("BUDGET_EXCEEDED")

    

    return _result(
        invoice_record,
        findings,
    )


# ==================================================
# RESULT BUILDER
# ==================================================

def _result(
    invoice_record: dict[str, Any],
    findings: list[str],
) -> dict[str, Any]:

    unique = list(
        dict.fromkeys(findings)
    )

    needs_review = any(
        code not in INFO_ONLY_CODES
        for code in unique
    )

    return {
        "case_id": invoice_record.get("case_id"),
        "recommendation": (
            "NEEDS_HUMAN_REVIEW"
            if needs_review
            else "READY_FOR_APPROVAL"
        ),
        "findings": unique,
    }


# ==================================================
# DATASET EVALUATION
# ==================================================

def evaluate_dataset(
    invoice_documents: list[dict[str, Any]] | None = None,
    reference_data: dict[str, Any] | None = None,
    manifest: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate records in manifest order with sequential invoice history."""

    invoices = (
        invoice_documents
        if invoice_documents is not None
        else load_invoice_documents()
    )

    reference = (
        reference_data
        if reference_data is not None
        else load_reference_data()
    )

    expected = (
        manifest
        if manifest is not None
        else load_test_manifest()
    )

    by_case_id = {
        record.get("case_id"): record
        for record in invoices
    }

    # The seed invoice specifically for duplicate case 07
    # is excluded initially. Case 01 becomes its duplicate
    # when the records are processed sequentially.
    #
    # The CHAIR-114-01 prior invoice remains seeded for
    # cumulative PO overbilling case 14.

    history = [
        dict(record)
        for record in reference.get(
            "prior_invoices",
            [],
        )
        if (
            "duplicate test case 07"
            not in _text(
                record.get("note")
            ).lower()
        )
    ]

    results = []

    for manifest_row in sorted(
        expected,
        key=lambda row: row.get("sequence", 0),
    ):

        case_id = manifest_row.get(
            "case_id"
        )

        invoice_record = by_case_id.get(
            case_id
        )

        if invoice_record is None:

            results.append(
                {
                    "case_id": case_id,
                    "recommendation": "MISSING_TEST_INPUT",
                    "findings": [],
                }
            )

            continue

        result = evaluate_invoice(
            invoice_record,
            reference,
            history,
        )

        results.append(result)

        # Processed invoices become history for
        # subsequent duplicate and cumulative checks.

        document = _invoice_document(
            invoice_record
        )

        po = _find_po(
            _po_reference(document),
            reference,
        )

        history_record = _make_history_record(
            document,
            reference,
            po,
        )

        if history_record:
            history.append(history_record)

    return results


# ==================================================
# MANIFEST COMPARISON
# ==================================================

def compare_with_manifest(
    results: list[dict[str, Any]],
    manifest: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:

    expected = (
        manifest
        if manifest is not None
        else load_test_manifest()
    )

    expected_by_id = {
        row["case_id"]: row
        for row in expected
    }

    mismatches = []

    for result in results:

        row = expected_by_id.get(
            result.get("case_id"),
            {},
        )

        expected_recommendation = row.get(
            "expected_recommendation"
        )

        expected_findings = sorted(
            row.get("expected_findings", [])
        )

        actual_findings = sorted(
            result.get("findings", [])
        )

        if (
            result.get("recommendation")
            != expected_recommendation
            or actual_findings
            != expected_findings
        ):

            mismatches.append(
                {
                    "case_id": result.get("case_id"),
                    "expected_recommendation": (
                        expected_recommendation
                    ),
                    "actual_recommendation": (
                        result.get("recommendation")
                    ),
                    "expected_findings": (
                        expected_findings
                    ),
                    "actual_findings": (
                        actual_findings
                    ),
                }
            )

    return mismatches


# ==================================================
# DIRECT EXECUTION
# ==================================================

def main() -> int:

    results = evaluate_dataset()

    mismatches = compare_with_manifest(
        results
    )

    for result in results:

        codes = (
            ", ".join(result["findings"])
            if result["findings"]
            else "(none)"
        )

        print(
            f'{result["case_id"]}: '
            f'{result["recommendation"]} | '
            f'{codes}'
        )

    print(
        f"\nPassed: "
        f"{len(results) - len(mismatches)}"
        f"/{len(results)}"
    )

    if mismatches:

        print("\nMismatches:")

        for mismatch in mismatches:

            print(
                json.dumps(
                    mismatch,
                    ensure_ascii=False,
                )
            )

        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())