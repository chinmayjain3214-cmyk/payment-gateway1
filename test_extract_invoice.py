import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import extract_invoice as extractor


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append(model)
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return FakeResponse('{"invoice_number": "INV-TEST"}')


class FakeClient:
    def __init__(self, responses):
        self.models = FakeModels(responses)


class InvoiceExtractionTests(unittest.TestCase):
    def test_missing_fields_are_kept_as_missing(self):
        result = extractor.normalize_invoice_data({})
        self.assertIsInstance(result, dict)
        self.assertIsNone(result.get("invoice_number"))
        self.assertIsNone(result.get("vendor"))
        self.assertIsNone(result.get("po_number"))
        self.assertIsNone(result.get("currency"))
        self.assertEqual(result.get("items"), [])

    def test_alternate_field_names_are_normalized(self):
        raw = {
            "invoice_no": "INV-123",
            "supplier_name": "Example Supplier",
            "GSTIN": " abcd1234 ",
            "purchase_order_reference": "PO/2026-01",
            "currency_code": "INR",
            "line_items": [
                {
                    "description": "Paper",
                    "qty": 2,
                    "rate": 10,
                    "line_amount": 20,
                }
            ],
            "grand_total": 20,
        }
        result = extractor.normalize_invoice_data(raw)
        self.assertEqual(result["invoice_number"], "INV-123")
        self.assertEqual(result["vendor"], "Example Supplier")
        self.assertEqual(result["gstin"], "ABCD1234")
        self.assertEqual(result["po_number"], "PO/2026-01")
        self.assertEqual(result["currency"], "INR")
        self.assertEqual(result["items"][0]["quantity"], 2)
        self.assertEqual(result["items"][0]["unit_price"], 10)
        self.assertEqual(result["items"][0]["line_total"], 20)
        self.assertEqual(result["total"], 20)

    def test_individual_gst_components_are_not_duplicated(self):
        result = extractor.normalize_invoice_data({
            "cgst": 9,
            "sgst": 9,
            "igst": None,
            "tax": 18,
            "tax_amount": 18,
        })
        self.assertEqual(result["cgst"], 9)
        self.assertEqual(result["sgst"], 9)
        self.assertNotIn("tax", result)
        self.assertNotIn("tax_amount", result)

    def test_combined_tax_is_preserved_when_components_are_absent(self):
        result = extractor.normalize_invoice_data({"tax_amount": 18})
        self.assertEqual(result["tax"], 18)
        self.assertNotIn("tax_amount", result)

    def test_malformed_json_uses_configured_attempts_and_returns_none(self):
        fake_client = FakeClient([
            FakeResponse("not valid JSON"),
            FakeResponse("still not valid JSON"),
        ])
        with tempfile.TemporaryDirectory() as directory:
            invoice_path = Path(directory) / "broken.pdf"
            invoice_path.write_bytes(b"synthetic test bytes")
            with patch.object(extractor, "client", fake_client), \
                 patch.object(extractor, "MODELS", ["primary-test", "backup-test"]), \
                 patch.object(extractor, "MAX_ATTEMPTS", 2), \
                 patch.object(extractor.time, "sleep", return_value=None):
                result = extractor.extract_invoice(str(invoice_path))

        self.assertIsNone(result)
        self.assertEqual(fake_client.models.calls, ["primary-test", "backup-test"])

    def test_model_service_errors_use_backup_and_return_none(self):
        fake_client = FakeClient([
            TimeoutError("simulated model timeout"),
            RuntimeError("simulated backup failure"),
        ])
        with tempfile.TemporaryDirectory() as directory:
            invoice_path = Path(directory) / "service-error.pdf"
            invoice_path.write_bytes(b"synthetic test bytes")
            with patch.object(extractor, "client", fake_client), \
                 patch.object(extractor, "MODELS", ["primary-test", "backup-test"]), \
                 patch.object(extractor, "MAX_ATTEMPTS", 2), \
                 patch.object(extractor.time, "sleep", return_value=None):
                result = extractor.extract_invoice(str(invoice_path))

        self.assertIsNone(result)
        self.assertEqual(fake_client.models.calls, ["primary-test", "backup-test"])

    def test_missing_file_returns_none_without_calling_model(self):
        fake_client = FakeClient([])
        missing_path = Path(tempfile.gettempdir()) / "definitely_missing_test_invoice.pdf"
        if missing_path.exists():
            missing_path.unlink()
        with patch.object(extractor, "client", fake_client):
            result = extractor.extract_invoice(str(missing_path))
        self.assertIsNone(result)
        self.assertEqual(fake_client.models.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
