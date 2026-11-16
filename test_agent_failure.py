"""Offline test for the agent's final fail-safe path.

This test mocks Gemini, audit logging, and approval persistence. It makes no
network calls and does not create a real approval request.

Run from the project root:
    python -m pytest -v test_agent_retry.py test_agent_failure.py
"""

from unittest.mock import patch

import agent


class _FailingChat:
    def send_message(self, _prompt):
        raise TimeoutError("simulated Gemini timeout")


class _FakeChats:
    def __init__(self):
        self.created_models = []

    def create(self, model, config):
        self.created_models.append(model)
        return _FailingChat()


class _FakeClient:
    def __init__(self):
        self.chats = _FakeChats()


def test_all_gemini_attempts_fail_and_agent_falls_back_to_human_review():
    fake_client = _FakeClient()
    expected_outcome = {
        "summary": "fallback",
        "recommendation": "NEEDS_HUMAN_REVIEW",
        "approval_request_id": 999,
        "findings": ["INCOMPLETE_EXTRACTION"],
    }
    logged_events = []

    with (
        patch.object(agent, "client", fake_client),
        patch.object(agent, "MODELS", ["primary-model", "backup-model"]),
        patch.object(agent, "MAX_ATTEMPTS", 2),
        patch.object(agent, "start_run"),
        patch.object(
            agent,
            "_safe_log",
            side_effect=lambda event, detail: logged_events.append((event, detail)),
        ),
        patch.object(agent, "get_dataset_result", return_value=None),
        patch.object(agent, "record_outcome", return_value=expected_outcome) as save_outcome,
        patch.object(agent.time, "sleep"),
    ):
        result = agent.run_agent("simulated-invoice.pdf")

    assert fake_client.chats.created_models == ["primary-model", "backup-model"]
    assert sum(event == "agent:error" for event, _ in logged_events) == 2
    assert any(event == "agent:gave_up" for event, _ in logged_events)
    save_outcome.assert_called_once()

    args, kwargs = save_outcome.call_args
    assert args[0] == "simulated-invoice.pdf"
    assert "could not be completed" in args[1].lower()
    assert kwargs.get("force_human_review_reason")
    assert result == expected_outcome
