
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_invoices


class InvoiceCacheTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

        self.source = self.root / "invoice_test.pdf"
        self.source.write_bytes(b"original invoice")

        self.cache_dir = self.root / "data" / "invoices"

        self.sample_data = {
            "vendor": "Test Vendor",
            "invoice_number": "TEST-001",
            "total": 1180,
            "items": []
        }

        self.cache_patch = patch.object(
            run_invoices,
            "CACHE_DIR",
            self.cache_dir
        )
        self.cache_patch.start()

    def tearDown(self):
        self.cache_patch.stop()
        self.temp.cleanup()

    def test_new_extraction_is_cached(self):
        with patch.object(
            run_invoices,
            "extract_invoice",
            return_value=self.sample_data
        ) as mock_extract:

            result = run_invoices.get_invoice_data(self.source)

        self.assertEqual(result, self.sample_data)
        mock_extract.assert_called_once()

        cache_file = self.cache_dir / "invoice_test.pdf.json"
        self.assertTrue(cache_file.exists())

        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        self.assertEqual(cached["data"], self.sample_data)

    def test_valid_cache_is_reused(self):
        cache_file = self.cache_dir / "invoice_test.pdf.json"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        stat = self.source.stat()

        cache_file.write_text(
            json.dumps({
                "_cache_version": run_invoices.CACHE_VERSION,
                "_source_size": stat.st_size,
                "_source_mtime_ns": stat.st_mtime_ns,
                "data": self.sample_data
            }),
            encoding="utf-8"
        )

        with patch.object(
            run_invoices,
            "extract_invoice"
        ) as mock_extract:

            result = run_invoices.get_invoice_data(self.source)

        self.assertEqual(result, self.sample_data)
        mock_extract.assert_not_called()

    def test_modified_source_triggers_extraction(self):
        run_invoices.CACHE_DIR = self.cache_dir

        with patch.object(
            run_invoices,
            "extract_invoice",
            return_value=self.sample_data
        ):
            run_invoices.get_invoice_data(self.source)

        self.source.write_bytes(b"modified invoice with different size")

        updated_data = {
            **self.sample_data,
            "invoice_number": "TEST-002"
        }

        with patch.object(
            run_invoices,
            "extract_invoice",
            return_value=updated_data
        ) as mock_extract:

            result = run_invoices.get_invoice_data(self.source)

        self.assertEqual(result["invoice_number"], "TEST-002")
        mock_extract.assert_called_once()

    def test_corrupt_cache_is_regenerated(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        cache_file = self.cache_dir / "invoice_test.pdf.json"
        cache_file.write_text("{invalid json", encoding="utf-8")

        with patch.object(
            run_invoices,
            "extract_invoice",
            return_value=self.sample_data
        ) as mock_extract:

            result = run_invoices.get_invoice_data(self.source)

        self.assertEqual(result, self.sample_data)
        mock_extract.assert_called_once()

        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        self.assertEqual(cached["data"], self.sample_data)

    def test_cache_write_failure_preserves_extraction(self):
        with patch.object(
            run_invoices,
            "extract_invoice",
            return_value=self.sample_data
        ), patch(
            "run_invoices.tempfile.NamedTemporaryFile",
            side_effect=OSError("Simulated cache write failure")
        ):

            result = run_invoices.get_invoice_data(self.source)

        self.assertEqual(result, self.sample_data)

    def test_missing_invoice_returns_none(self):
        missing_file = self.root / "missing.pdf"

        with patch.object(
            run_invoices,
            "extract_invoice"
        ) as mock_extract:

            result = run_invoices.get_invoice_data(missing_file)

        self.assertIsNone(result)
        mock_extract.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
