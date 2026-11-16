
import unittest

from approval_evidence import build_approval_evidence


class DepartmentBudgetEvidenceTests(unittest.TestCase):
    FILE = "budget-test-invoice.pdf"

    def make_event(self, result, invoice_file=None):
        return {
            "id": 10,
            "step": "tool:check_department_budget",
            "detail": {
                "file": invoice_file or self.FILE,
                "result": result,
            },
        }

    def get_budget_card(self, result, invoice_file=None):
        cards = build_approval_evidence(
            self.FILE, [self.make_event(result, invoice_file)]
        )
        return next(
            card for card in cards
            if card["name"] == "Budget validation"
        )

    def test_department_budget_passed(self):
        card = self.get_budget_card({
            "budget_ok": True,
            "department_id": "DEPT-LIB",
            "budget_remaining": 90000.0,
            "invoice_total": 10.0,
            "note": "Invoice fits within the remaining Library budget.",
        })
        self.assertEqual(card["status"], "Within limit")
        self.assertEqual(card["kind"], "passed")
        self.assertIn("Library", card["detail"])

    def test_department_budget_exceeded(self):
        card = self.get_budget_card({
            "budget_ok": False,
            "note": "Invoice exceeds remaining budget by 5,000.00.",
        })
        self.assertEqual(card["status"], "Limit exceeded")
        self.assertEqual(card["kind"], "issue")

    def test_department_budget_unavailable_is_not_verified(self):
        card = self.get_budget_card({
            "budget_ok": None,
            "note": "Purchase order has no department_id; budget check skipped.",
        })
        self.assertEqual(card["status"], "Not verified")
        self.assertEqual(card["kind"], "warning")

    def test_other_invoice_budget_event_is_ignored(self):
        card = self.get_budget_card(
            {"budget_ok": True, "note": "Other invoice passed."},
            invoice_file="another-invoice.pdf",
        )
        self.assertEqual(card["status"], "Not verified")


if __name__ == "__main__":
    unittest.main()
