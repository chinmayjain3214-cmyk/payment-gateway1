"""Turns the agent's reason codes into readable labels for the approval screen."""

import html
import json
import re


REASONS = {
    "DUPLICATE_INVOICE": (
        "Duplicate invoice",
        "high",
        "This invoice number was already submitted by this vendor.",
    ),
    "BUDGET_EXCEEDED": (
        "Budget exceeded",
        "high",
        "The invoice total would push the department over its allocated budget."),

    "CANCELLED_PO": (
        "PO cancelled",
        "high",
        "The purchase order was cancelled, so nothing should be paid against it.",
    ),

    "GRN_QUANTITY_SHORTAGE": (
        "Billed more than received",
        "high",
        "The invoice bills more items than the goods receipt shows were accepted.",
    ),

    "CUMULATIVE_PO_OVERBILL": (
        "PO over-billed",
        "high",
        "Earlier invoices plus this one add up to more than the purchase order allows.",
    ),

    "PO_UNIT_PRICE_MISMATCH": (
        "Price differs from PO",
        "high",
        "The unit price on the invoice is not the approved price on the purchase order.",
    ),

    "VENDOR_PO_MISMATCH": (
        "Vendor differs from PO",
        "high",
        "The vendor identity on the invoice does not match the vendor assigned to the purchase order.",
    ),

    "VENDOR_GSTIN_MISMATCH": (
        "Vendor GSTIN mismatch",
        "high",
        "The GSTIN on the invoice does not match the vendor on record.",
    ),

    "MISSING_GOODS_RECEIPT": (
        "No goods receipt",
        "high",
        "There is no record that the goods were received.",
    ),

    "PO_REFERENCE_UNMAPPED": (
        "Unknown PO reference",
        "medium",
        "The invoice mentions an order number that does not match any known PO.",
    ),

    "MISSING_PO_REFERENCE": (
        "No PO on invoice",
        "medium",
        "The invoice does not show a purchase order number.",
    ),

    "INVOICE_ARITHMETIC_MISMATCH": (
        "Totals don't add up",
        "medium",
        "The invoice's own line totals, tax or grand total do not add up.",
    ),

    "GST_RATE_MISMATCH": (
        "Wrong GST rate",
        "medium",
        "The GST charged does not match the expected rate.",
    ),

    "FX_RATE_MISMATCH": (
        "Exchange rate differs",
        "medium",
        "The exchange rate used is different from the reference rate for that date.",
    ),

    "CREDIT_NOTE_SPECIAL_HANDLING": (
        "Credit note",
        "medium",
        "This is a credit note, not a normal invoice. A person must decide how to handle it.",
    ),

    "LOW_DOCUMENT_QUALITY": (
        "Poor scan quality",
        "medium",
        "The document is blurry, rotated or cut off, so it may have been read wrongly.",
    ),

    "INCOMPLETE_EXTRACTION": (
        "Some fields unreadable",
        "medium",
        "Some invoice details could not be read and need to be checked by hand.",
    ),

    "PRICE_VARIANCE_WITHIN_TOLERANCE": (
        "Small price difference (allowed)",
        "info",
        "The price is slightly different from the PO but inside the allowed tolerance. Noted only.",
    ),
}


NOT_REASONS = {
    "READY_FOR_APPROVAL",
    "NEEDS_HUMAN_REVIEW",
}


COLORS = {
    "high": ("#FDECEF", "#B8283F"),
    "medium": ("#FFF4DC", "#9A6200"),
    "info": ("#E8ECFE", "#3340F2"),
}


_CODE_PATTERN = re.compile(
    r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b"
)


def _as_text(value):
    if value is None:
        return ""

    if isinstance(value, (list, tuple, dict)):
        return json.dumps(
            value,
            ensure_ascii=False,
        )

    return str(value)


def extract_codes(value):
    """Return unique known or unknown reason codes in appearance order."""

    codes = []

    for code in _CODE_PATTERN.findall(
        _as_text(value)
    ):

        if code in NOT_REASONS:
            continue

        if code not in codes:
            codes.append(code)

    return codes


def reason_label(code):
    if code in REASONS:
        return REASONS[code][0]

    return code.replace(
        "_",
        " ",
    ).capitalize()


def reason_severity(code):
    if code in REASONS:
        return REASONS[code][1]

    return "medium"


def short_reasons(value):
    """One-line reason summary for tables."""

    text = _as_text(value).strip()

    codes = extract_codes(text)

    if codes:
        return ", ".join(
            reason_label(code)
            for code in codes
        )

    return (
        text[:120]
        + ("..." if len(text) > 120 else "")
    )


def badge_html(code):
    background, color = COLORS[
        reason_severity(code)
    ]

    return (
        "<span style='display:inline-block;"
        "margin:0 8px 8px 0;"
        "padding:4px 12px;"
        "border-radius:999px;"
        "font-size:0.85rem;"
        "font-weight:600;"
        "background:"
        + background
        + ";color:"
        + color
        + ";'>"
        + html.escape(reason_label(code))
        + "</span>"
    )


def render_reasons(value):
    """Show why the agent flagged an invoice."""

    import streamlit as st

    text = _as_text(value).strip()

    codes = extract_codes(text)

    if not codes:

        st.warning(
            "The agent flagged this invoice: "
            + (
                text
                or "No specific reason was provided."
            )
        )

        return

    informational_only = all(
        reason_severity(code) == "info"
        for code in codes
    )

    if informational_only:
        st.markdown("**Informational checks**")
    else:
        st.markdown("**Why it was flagged**")

    # Display badges for both blocking and informational findings.
    st.markdown(
        "".join(
            badge_html(code)
            for code in codes
        ),
        unsafe_allow_html=True,
    )

    for code in codes:

        if code in REASONS:

            st.caption(
                "**"
                + REASONS[code][0]
                + ":** "
                + REASONS[code][2]
            )

    leftover = _CODE_PATTERN.sub(
        "",
        text,
    )

    if re.search(
        r"[A-Za-z]{3,}",
        leftover,
    ):

        with st.expander(
            "Agent's full note"
        ):
            st.write(text)