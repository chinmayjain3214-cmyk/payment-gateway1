import unittest

from approval_workflow import (
    APPROVAL_STAGES,
    current_pending_stage,
    normalize_approval_role,
    role_can_act,
)


class ApprovalWorkflowPolicyTests(unittest.TestCase):
    def test_workflow_has_three_ordered_stages(self):
        self.assertEqual(
            [stage["stage_label"] for stage in APPROVAL_STAGES],
            ["Department Head", "Finance Officer", "Final Approver"],
        )
        self.assertEqual([stage["stage_order"] for stage in APPROVAL_STAGES], [1, 2, 3])

    def test_only_assigned_role_can_act_on_stage(self):
        self.assertTrue(role_can_act("department_head", "department_head"))
        self.assertFalse(role_can_act("finance_officer", "department_head"))
        self.assertFalse(role_can_act("approver", "finance_officer"))

    def test_legacy_approver_role_is_final_approver_alias(self):
        self.assertEqual(normalize_approval_role("approver"), "final_approver")
        self.assertTrue(role_can_act("approver", "final_approver"))
        self.assertTrue(role_can_act("final_approver", "final_approver"))

    def test_first_pending_stage_is_current(self):
        rows = [
            {"stage_order": 1, "status": "APPROVED", "stage_label": "Department Head"},
            {"stage_order": 2, "status": "PENDING", "stage_label": "Finance Officer"},
            {"stage_order": 3, "status": "PENDING", "stage_label": "Final Approver"},
        ]
        self.assertEqual(current_pending_stage(rows)["stage_label"], "Finance Officer")

    def test_no_pending_stage_after_all_approved_or_rejected(self):
        rows = [
            {"stage_order": 1, "status": "APPROVED"},
            {"stage_order": 2, "status": "APPROVED"},
            {"stage_order": 3, "status": "APPROVED"},
        ]
        self.assertIsNone(current_pending_stage(rows))
        rows[1]["status"] = "REJECTED"
        self.assertIsNone(current_pending_stage(rows))


if __name__ == "__main__":
    unittest.main()
