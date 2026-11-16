import json
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

client = (
    genai.Client(
        api_key=API_KEY,
        http_options={"timeout": 45000},
    )
    if API_KEY
    else None
)

# Model configuration
MAIN_MODEL = (os.getenv("MODEL") or "gemini-3.1-flash-lite").strip()

fallback_candidates = (
    os.getenv("FALLBACK_MODELS", "").split(",")
    + [os.getenv("FALLBACK_MODEL", "")]
)

MODELS = []
for model_name in [MAIN_MODEL] + fallback_candidates:
    model_name = model_name.strip()
    if model_name and model_name not in MODELS:
        MODELS.append(model_name)

MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "2"))

if MAX_ATTEMPTS < 1:
    raise ValueError("MAX_ATTEMPTS must be at least 1")

WAIT_SECONDS = [3, 8, 15]

# Ask for both the existing invoice fields and the additional
# fields required by the procurement dataset.
PROMPT = """
Read the supplied invoice or credit note carefully.

Return valid JSON only. Do not include Markdown or explanations.

Use this structure. Use null for any field that is not present or cannot
be read. Do not use 0 as a placeholder for missing amounts or quantities.

{
    "document_type": null,
    "invoice_number": null,
    "credit_note_number": null,
    "invoice_date": null,
    "date": null,
    "vendor": null,
    "vendor_name": null,
    "gstin": null,
    "po_reference": null,
    "po_number": null,
    "currency": null,
    "items": [
        {
            "name": null,
            "description": null,
            "quantity": null,
            "unit": null,
            "unit_price": null,
            "line_total": null,
            "amount": null,
            "discount_percent": null,
            "tax_percent": null
        }
    ],
    "subtotal": null,
    "cgst": null,
    "sgst": null,
    "igst": null,
    "tax": null,
    "tax_amount": null,
    "shipping": null,
    "discount": null,
    "total": null,
    "exchange_rate": null,
    "service_details": {
        "hours": null
    }
}

IMPORTANT RULES:

1. Extract PO references from anywhere on the document, including
   reference details and customer order fields.
2. Do not confuse an invoice number with a PO number.
3. Extract GSTIN separately from the vendor name.
4. Extract the currency exactly as printed. Use a currency code such as
   INR or USD when it is clear from the document.
5. Identify credit notes and extract their credit note number.
6. Preserve negative amounts on credit notes.
7. Extract quantities, unit prices and line totals separately.
8. Preserve discounts and individual tax components.
9. Do not invent missing information.
10. Use null for missing fields. Do not replace missing numbers with zero.
11. Use numeric values for amounts and quantities where possible.
12. Do not silently correct spelling or identifiers.
13. Keep PO references exactly as printed, including slashes, hyphens
    and other characters.
14. If individual CGST, SGST or IGST amounts are available, extract
    those amounts separately. Do not also repeat their sum in tax or
    tax_amount. If only a combined GST/tax amount is shown, put it in
    tax and leave cgst, sgst and igst null.
15. Do not calculate tax amounts that are not printed on the document.
"""

SUPPORTED_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _pick(data, *keys):
    """Return the first available non-empty field."""
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return None


def normalize_invoice_data(raw):
    """Normalize extracted field names while preserving source values.

    The result remains compatible with the existing invoice checks and
    includes the additional fields required by the procurement dataset.
    """
    if isinstance(raw, list):
        return [normalize_invoice_data(item) for item in raw]

    if not isinstance(raw, dict):
        return None

    data = dict(raw)

    # Vendor information
    vendor_raw = _pick(
        data,
        "vendor",
        "vendor_name",
        "supplier_name",
        "supplier",
    )

    if isinstance(vendor_raw, dict):
        vendor_name = _pick(
            vendor_raw,
            "name",
            "vendor_name",
            "supplier_name",
        )
        gstin = _pick(vendor_raw, "gstin", "GSTIN")
    else:
        vendor_name = vendor_raw
        gstin = None

    gstin = gstin or _pick(data, "gstin", "GSTIN")

    data["vendor"] = vendor_name
    data["vendor_name"] = vendor_name

    if gstin is not None:
        data["gstin"] = str(gstin).strip().upper()

    # Invoice number and date
    invoice_number = _pick(
        data,
        "invoice_number",
        "invoice_no",
        "invoice_id",
        "document_id",
    )
    data["invoice_number"] = invoice_number

    invoice_date = _pick(
        data,
        "invoice_date",
        "date",
        "issue_date",
    )
    data["invoice_date"] = invoice_date
    data["date"] = invoice_date

    # PO reference
    po_reference = _pick(
        data,
        "po_reference",
        "po_number",
        "purchase_order",
        "purchase_order_reference",
        "reference_po",
        "purchase_reference",
    )

    if po_reference is None:
        details = data.get("reference_details")
        if isinstance(details, dict):
            reference_type = str(details.get("reference_type") or "").lower()
            if "purchase order" in reference_type or reference_type == "po":
                po_reference = details.get("customer_order")

    data["po_reference"] = po_reference
    data["po_number"] = po_reference

    # Currency and document type
    data["currency"] = _pick(data, "currency", "currency_code")
    data["document_type"] = _pick(data, "document_type", "doc_type", "invoice_type")

    data["credit_note_number"] = _pick(
        data,
        "credit_note_number",
        "credit_note_no",
    )

    data["exchange_rate"] = _pick(data, "exchange_rate", "fx_rate")

    # Item normalization
    raw_items = _pick(data, "items", "products", "line_items")
    normalized_items = []

    if isinstance(raw_items, list):
        for original_item in raw_items:
            if not isinstance(original_item, dict):
                continue

            item = dict(original_item)

            name = _pick(
                item,
                "description",
                "name",
                "product_name",
                "service_name",
            )
            quantity = _pick(item, "quantity", "qty", "quantity_billed")
            unit_price = _pick(item, "unit_price", "unit_rate", "rate", "price")
            amount = _pick(
                item,
                "amount",
                "line_total",
                "line_amount",
                "total",
                "credit_amount",
            )

            item["name"] = name
            item["description"] = name
            item["quantity"] = quantity
            item["unit_price"] = unit_price
            item["line_total"] = amount
            item["amount"] = amount

            normalized_items.append(item)

    data["items"] = normalized_items

    # Financial fields
    data["subtotal"] = _pick(data, "subtotal", "net_payable")
    data["total"] = _pick(
        data,
        "total",
        "grand_total",
        "invoice_total",
        "amount_due",
        "net_payable",
        "total_credit",
    )

    # Avoid storing the same GST twice. If individual GST components are
    # present, keep those and remove the combined aliases. Otherwise keep
    # just one combined tax field.
    tax_components = [
        data.get("cgst"),
        data.get("sgst"),
        data.get("igst"),
    ]
    has_tax_components = any(value is not None for value in tax_components)

    if has_tax_components:
        data.pop("tax", None)
        data.pop("tax_amount", None)
        data.pop("gst", None)
    else:
        combined_tax = _pick(data, "tax", "tax_amount", "gst")

        data.pop("tax_amount", None)
        data.pop("gst", None)

        if combined_tax is not None:
            data["tax"] = combined_tax
        else:
            data.pop("tax", None)

    data["shipping"] = _pick(data, "shipping", "freight")
    data["discount"] = _pick(data, "discount", "discount_amount")

    return data


def extract_invoice(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    mime_type = SUPPORTED_TYPES.get(ext)

    if mime_type is None:
        raise ValueError("Unsupported file type: " + ext)

    if client is None:
        raise ValueError("GEMINI_API_KEY is missing from the .env file.")

    # Safely read the invoice file.
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

    except OSError as e:
        print(
            "[extraction error] Could not read invoice:",
            str(e)[:150],
        )
        return None

    file_part = types.Part.from_bytes(
        data=file_bytes,
        mime_type=mime_type,
    )

    for attempt in range(1, MAX_ATTEMPTS + 1):
        model = MODELS[(attempt - 1) % len(MODELS)]

        try:
            response = client.models.generate_content(
                model=model,
                contents=[file_part, PROMPT],
                config={"response_mime_type": "application/json"},
            )

            if not response.text:
                raise ValueError("The model returned an empty response.")

            extracted = json.loads(response.text)
            normalized = normalize_invoice_data(extracted)

            if normalized is None:
                raise ValueError(
                    "The extracted response was not a JSON object or list."
                )

            return normalized

        except Exception as e:
            print(
                "Reading attempt",
                attempt,
                "with",
                model,
                "failed:",
                str(e)[:150],
            )

            if attempt < MAX_ATTEMPTS:
                time.sleep(
                    WAIT_SECONDS[
                        min(attempt - 1, len(WAIT_SECONDS) - 1)
                    ]
                )

    return None


if __name__ == "__main__":
    invoice_dir = "invoices"

    if not os.path.isdir(invoice_dir):
        raise FileNotFoundError(
            "The 'invoices' folder was not found. Run this script from the project root."
        )

    for name in sorted(os.listdir(invoice_dir)):
        if os.path.splitext(name)[1].lower() in SUPPORTED_TYPES:
            print("=== " + name + " ===")
            result = extract_invoice(os.path.join(invoice_dir, name))

            if result is None:
                print("Could not read this invoice.")
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
