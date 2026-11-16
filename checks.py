import difflib
import re

def to_number(value):
    """Turn 1,234.50 or a currency string or a plain number into a float. Returns None if it can't."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = "".join(ch for ch in str(value) if ch.isdigit() or ch in ".-")
    try:
        return float(cleaned)
    except ValueError:
        return None



def check_line_math(invoice):
    """Check item arithmetic and invoice total, including individual GST components."""

    issues = []
    line_sum = 0.0

    # 1. Check each item's quantity x unit price.
    for item in invoice.get("items") or []:
        name = item.get("name", "?")
        qty = to_number(item.get("quantity"))
        price = to_number(item.get("unit_price"))
        line_total = to_number(item.get("line_total"))

        if qty is None or price is None or line_total is None:
            issues.append({
                "type": "MISSING_VALUE",
                "detail": f"Item '{name}' is missing a quantity, price or line total."
            })
            continue

        line_sum += line_total
        expected = round(qty * price, 2)

        if abs(expected - line_total) > 0.01:
            issues.append({
                "type": "LINE_MATH",
                "detail": f"Item '{name}': {qty:g} x {price:g} = {expected:g}, but the invoice says {line_total:g}."
            })

    # 2. Check invoice total.
    total = to_number(invoice.get("total"))

    if total is None:
        issues.append({
            "type": "MISSING_VALUE",
            "detail": "Invoice total is missing."
        })
        return issues

    # 3. Read individual GST components when available.
    tax_keys = ("cgst", "sgst", "igst")
    raw_components = [invoice.get(key) for key in tax_keys]
    tax_components = [to_number(value) for value in raw_components]

    components_present = any(
        value is not None and str(value).strip() != ""
        for value in raw_components
    )

    if components_present:
        # Avoid counting GST twice if a combined tax field also exists.
        for key, raw_value, parsed_value in zip(
            tax_keys, raw_components, tax_components
        ):
            if (
                raw_value is not None
                and str(raw_value).strip() != ""
                and parsed_value is None
            ):
                issues.append({
                    "type": "MISSING_VALUE",
                    "detail": f"GST component '{key}' could not be read."
                })

        tax = sum(
            value for value in tax_components
            if value is not None
        )

    else:
        # Fall back to combined GST for older invoice formats.
        tax = to_number(invoice.get("tax"))

        if tax is None:
            tax = to_number(invoice.get("tax_amount"))

        if tax is None:
            tax = to_number(invoice.get("gst"))

        if tax is None:
            tax = 0.0

    # 4. Add shipping and subtract discounts.
    shipping = to_number(invoice.get("shipping")) or 0.0
    discount = to_number(invoice.get("discount")) or 0.0

    expected_total = round(
        line_sum + tax + shipping - discount, 2
    )

    if abs(expected_total - total) > 0.01:
        diff = round(total - expected_total, 2)

        issues.append({
            "type": "TOTAL_MISMATCH",
            "detail": (
                f"Items {line_sum:g} + tax {tax:g} + "
                f"shipping {shipping:g} - discount {discount:g} = "
                f"{expected_total:g}, but the invoice total is "
                f"{total:g} (difference {diff:g})."
            )
        })

    return issues




def _normalize_vendor(value):
    """Normalize a vendor ID or the company-name part of an extracted value."""
    import re

    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def _vendor_company_name(value):
    """Discard address/GST metadata appended below the extracted company name."""
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
    return lines[0] if lines else ""


def check_vendor(
    invoice_vendor,
    po_vendor,
    invoice_vendor_id=None,
    po_vendor_id=None
):
    """Compare explicit vendor IDs first, then clean company names."""
    invoice_name = _vendor_company_name(invoice_vendor)
    po_name = _vendor_company_name(po_vendor)

    invoice_id = _normalize_vendor(invoice_vendor_id)
    po_id = _normalize_vendor(po_vendor_id)

    if invoice_id and po_id:
        if invoice_id != po_id:
            return {
                "status": "mismatch",
                "note": (
                    f"Invoice vendor ID '{invoice_vendor_id}' does not match "
                    f"PO vendor ID '{po_vendor_id}'."
                ),
            }

        # Even when IDs match, a clearly different company name should be reviewed.
        if invoice_name and po_name:
            if _normalize_vendor(invoice_name) != _normalize_vendor(po_name):
                return {
                    "status": "mismatch",
                    "note": (
                        f"Invoice vendor name '{invoice_name}' does not match "
                        f"PO vendor name '{po_name}'."
                    ),
                }

        return {
            "status": "match",
            "note": f"Vendor ID '{invoice_vendor_id}' matches the PO.",
        }

    if invoice_name and po_name:
        if _normalize_vendor(invoice_name) == _normalize_vendor(po_name):
            return {
                "status": "match",
                "note": f"'{invoice_name}' matches '{po_name}'.",
            }
        return {
            "status": "mismatch",
            "note": (
                f"Invoice vendor '{invoice_name}' does not match "
                f"PO vendor '{po_name}'."
            ),
        }

    return {
        "status": "cannot_check",
        "note": "Vendor identity could not be verified because the invoice or PO vendor details are missing.",
    }
