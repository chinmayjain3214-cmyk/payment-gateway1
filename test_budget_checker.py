import unittest
from unittest.mock import patch

import agent_tools


class DepartmentBudgetCheckerTests(unittest.TestCase):
    FILE = "budget-check-test.pdf"

    def setUp(self):
        # Clear per-invoice cached results between tests.
        agent_tools.start_run(self.FILE)

    @patch("agent_tools.log_step")
    @patch("agent_tools.load_reference_data")
    @patch("agent_tools.find_po")
    @patch("agent_tools._load_invoice")
    def test_missing_budget_consumed_returns_not_verified(
        self, mock_invoice, mock_find_po, mock_reference, mock_log
    ):
        mock_invoice.return_value = {
            "po_number": "PO-121",
            "total_amount": 100.0,
        }
        mock_find_po.return_value = {
            "status": "found",
            "po": {
                "po_number": "PO-121",
                "department_id": "DEPT-LIB",
            },
        }
        mock_reference.return_value = {
            "departments": [{
                "department_id": "DEPT-LIB",
                "name": "Library",
                "budget_allocated": 1000.0,
                # budget_consumed deliberately missing
            }]
        }

        result = agent_tools.check_department_budget(self.FILE)

        self.assertIsNone(result["budget_ok"])
        self.assertIn("budget_consumed", result["note"])

    @patch("agent_tools.log_step")
    @patch("agent_tools.load_reference_data")
    @patch("agent_tools.find_po")
    @patch("agent_tools._load_invoice")
    def test_zero_budget_consumed_is_a_valid_value(
        self, mock_invoice, mock_find_po, mock_reference, mock_log
    ):
        mock_invoice.return_value = {
            "po_number": "PO-121",
            "total_amount": 100.0,
        }
        mock_find_po.return_value = {
            "status": "found",
            "po": {
                "po_number": "PO-121",
                "department_id": "DEPT-LIB",
            },
        }
        mock_reference.return_value = {
            "departments": [{
                "department_id": "DEPT-LIB",
                "name": "Library",
                "budget_allocated": 1000.0,
                "budget_consumed": 0.0,
            }]
        }

        result = agent_tools.check_department_budget(self.FILE)

        self.assertIs(result["budget_ok"], True)
        self.assertEqual(result["budget_remaining"], 1000.0)


if __name__ == "__main__":
    unittest.main()
