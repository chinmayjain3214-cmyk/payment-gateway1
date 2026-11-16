"""Offline tests for agent timeout retry behaviour.

These tests mock Gemini and the database-facing outcome writer. They do not
make network calls, process an invoice, or create approval requests.
Run from the project root: python test_agent_retry.py
"""

import unittest
from unittest.mock import patch

import agent


class _FakeResponse:
    text = "Mocked successful AI summary"


class _FakeChat:
    def __init__(self, send_message):
        self._send_message = send_message

    def send_message(self, prompt):
        return self._send_message(prompt)


class _FakeChats:
    def __init__(self, create_chat):
        self._create_chat = create_chat

    def create(self, model, config):
        return self._create_chat(model, config)


class _FakeClient:
    def __init__(self, chats):
        self.chats = chats


class AgentRetryTests(unittest.TestCase):
    def test_does_not_retry_after_dataset_result_exists(self):
        state = {"dataset_result": None, "chat_creations": 0}
        expected_outcome = {
            "summary": "Fallback summary",
            "recommendation": "NEEDS_HUMAN_REVIEW",
            "approval_request_id": 123,
            "findings": ["PO_REFERENCE_UNMAPPED"],
        }

        def create_chat(model, config):
            state["chat_creations"] += 1

            def send_message(prompt):
                # Simulate tools completing before Gemini's final response times out.
                state["dataset_result"] = {
                    "recommendation": "NEEDS_HUMAN_REVIEW",
                    "findings": ["PO_REFERENCE_UNMAPPED"],
                }
                raise TimeoutError("simulated 504 after dataset checks")

            return _FakeChat(send_message)

        fake_client = _FakeClient(_FakeChats(create_chat))

        with (
            patch.object(agent, "client", fake_client),
            patch.object(agent, "MODELS", ["primary-model", "backup-model"]),
            patch.object(agent, "MAX_ATTEMPTS", 2),
            patch.object(agent, "start_run"),
            patch.object(agent, "log_step"),
            patch.object(
                agent,
                "get_dataset_result",
                side_effect=lambda _file_name: state["dataset_result"],
            ),
            patch.object(
                agent,
                "record_outcome",
                return_value=expected_outcome,
            ) as record_outcome,
        ):
            result = agent.run_agent("simulated-invoice.pdf")

        self.assertEqual(state["chat_creations"], 1)
        record_outcome.assert_called_once()
        self.assertEqual(result, expected_outcome)

    def test_uses_backup_model_if_first_attempt_fails_before_dataset_result(self):
        state = {"models_used": []}
        expected_outcome = {
            "summary": "Mocked successful AI summary",
            "recommendation": "READY_FOR_APPROVAL",
            "approval_request_id": 124,
            "findings": [],
        }

        def create_chat(model, config):
            state["models_used"].append(model)

            if model == "primary-model":
                def fail_before_tools(prompt):
                    raise TimeoutError("simulated early 504")
                return _FakeChat(fail_before_tools)

            return _FakeChat(lambda prompt: _FakeResponse())

        fake_client = _FakeClient(_FakeChats(create_chat))

        with (
            patch.object(agent, "client", fake_client),
            patch.object(agent, "MODELS", ["primary-model", "backup-model"]),
            patch.object(agent, "MAX_ATTEMPTS", 2),
            patch.object(agent, "start_run"),
            patch.object(agent, "log_step"),
            patch.object(agent, "get_dataset_result", return_value=None),
            patch.object(
                agent,
                "record_outcome",
                return_value=expected_outcome,
            ) as record_outcome,
            patch.object(agent.time, "sleep"),
        ):
            result = agent.run_agent("simulated-invoice.pdf")

        self.assertEqual(state["models_used"], ["primary-model", "backup-model"])
        record_outcome.assert_called_once()
        self.assertEqual(result, expected_outcome)


if __name__ == "__main__":
    unittest.main(verbosity=2)
