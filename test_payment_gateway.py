"""Tests for the sandbox payment gateway and gateway payment recording."""

import sys
import types
from datetime import date
from decimal import Decimal

import pytest

import payment_gateway as pgw

# db_store imports db, which imports psycopg2. These tests use a fake
# connection, so a stand-in module is enough when psycopg2 is absent.
try:
    import psycopg2  # noqa: F401
except ImportError:
    sys.modules["psycopg2"] = types.ModuleType("psycopg2")

import db_store


TODAY = date(2026, 11, 16)


def scheduled_payment(**overrides):
    row = {
        "id": 7,
        "approval_request_id": 42,
        "vendor_name": "Nova Computer Systems",
        "invoice_number": "clean_match.pdf",
        "department_id": "DEPT-IT",
        "invoice_amount": Decimal("5900.00"),
        "payment_status": "SCHEDULED",
    }
    row.update(overrides)
    return row


GOOD_CARD = {
    "card_number": "4111 1111 1111 1111",
    "name_on_card": "Test Payer",
    "expiry": "12/30",
    "cvv": "123",
}


# ---------- gateway ----------

def test_create_order_uses_schedule_amount():
    order = pgw.create_order(scheduled_payment())
    assert order["amount"] == Decimal("5900.00")
    assert order["amount_paise"] == 590000
    assert order["currency"] == "INR"
    assert order["order_id"].startswith("order_")


@pytest.mark.parametrize("status", ["PAID", "CANCELLED", ""])
def test_create_order_rejects_non_scheduled(status):
    with pytest.raises(pgw.PaymentValidationError):
        pgw.create_order(scheduled_payment(payment_status=status))


def test_create_order_rejects_zero_amount():
    with pytest.raises(pgw.PaymentValidationError):
        pgw.create_order(scheduled_payment(invoice_amount=0))


def test_card_success_stores_only_last_four():
    order = pgw.create_order(scheduled_payment())
    result = pgw.charge(order, "CARD", GOOD_CARD, today=TODAY)
    assert result["status"] == "SUCCESS"
    assert result["transaction_id"].startswith("PGW-")
    assert len(result["transaction_id"]) <= 50
    assert result["card_last4"] == "1111"
    assert "4111111111111111" not in str(result)
    assert "cvv" not in result
    assert "_test_outcome" not in result


def test_decline_test_card_fails():
    order = pgw.create_order(scheduled_payment())
    details = dict(GOOD_CARD, card_number="4000 0000 0000 0002")
    result = pgw.charge(order, "CARD", details, today=TODAY)
    assert result["status"] == "FAILED"
    assert result["transaction_id"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("card_number", "4111 1111 1111 1112"),  # fails Luhn
        ("card_number", "abcd"),
        ("expiry", "13/30"),
        ("expiry", "01/25"),  # expired
        ("cvv", "12"),
        ("name_on_card", ""),
    ],
)
def test_card_input_validation(field, value):
    order = pgw.create_order(scheduled_payment())
    with pytest.raises(pgw.PaymentValidationError):
        pgw.charge(order, "CARD", dict(GOOD_CARD, **{field: value}), today=TODAY)


def test_upi_success_and_failure():
    order = pgw.create_order(scheduled_payment())
    assert pgw.charge(order, "UPI", {"vpa": "success@sandbox"})["status"] == "SUCCESS"
    assert pgw.charge(order, "UPI", {"vpa": "failure@sandbox"})["status"] == "FAILED"
    with pytest.raises(pgw.PaymentValidationError):
        pgw.charge(order, "UPI", {"vpa": "not-a-vpa"})


def test_netbanking():
    order = pgw.create_order(scheduled_payment())
    assert pgw.charge(order, "NETBANKING", {"bank": "HDFC Bank"})["status"] == "SUCCESS"
    assert pgw.charge(order, "NETBANKING", {"bank": "Sandbox Bank (decline)"})["status"] == "FAILED"
    with pytest.raises(pgw.PaymentValidationError):
        pgw.charge(order, "NETBANKING", {"bank": "Unknown Bank"})


def test_unknown_method_rejected():
    order = pgw.create_order(scheduled_payment())
    with pytest.raises(pgw.PaymentValidationError):
        pgw.charge(order, "CRYPTO", {})


# ---------- recording ----------

class FakeCursor:
    def __init__(self, state):
        self.state = state
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        self.state["sql"].append(sql)
        if sql.startswith("SELECT approval_request_id, invoice_amount"):
            payment = self.state["payment"]
            self._row = (payment["approval_request_id"], payment["invoice_amount"]) if payment else None
        elif sql.startswith("SELECT to_regclass"):
            self._row = ("approval_workflow_stages",)
        elif "FROM approval_workflow_stages" in sql:
            self._row = (self.state["final_approver"],)
        elif sql.startswith("UPDATE payment_schedules"):
            payment = self.state["payment"]
            if payment["payment_status"] == "SCHEDULED":
                payment["payment_status"] = "PAID"
                payment["payment_batch_id"] = params[1]
                self._row = (payment["invoice_number"],)
            else:
                self._row = None
        else:
            self._row = None

    def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self, state):
        self.state = state

    def cursor(self):
        return FakeCursor(self.state)

    def commit(self):
        self.state["committed"] += 1

    def rollback(self):
        self.state["rolled_back"] += 1

    def close(self):
        pass


@pytest.fixture
def fake_db(monkeypatch):
    state = {
        "payment": scheduled_payment(),
        "final_approver": "fa_user",
        "sql": [],
        "committed": 0,
        "rolled_back": 0,
        "logs": [],
    }
    monkeypatch.setattr(db_store, "get_connection", lambda: FakeConnection(state))
    monkeypatch.setattr(db_store, "save_log", lambda step, detail: state["logs"].append((step, detail)) or True)
    return state


def successful_result():
    order = pgw.create_order(scheduled_payment())
    return pgw.charge(order, "UPI", {"vpa": "success@sandbox"})


def test_final_approver_who_approved_can_pay(fake_db):
    result = successful_result()
    invoice = db_store.record_gateway_payment(7, result, "fa_user", actor_role="final_approver")
    assert invoice == "clean_match.pdf"
    assert fake_db["payment"]["payment_status"] == "PAID"
    assert fake_db["payment"]["payment_batch_id"] == result["transaction_id"]
    step, detail = fake_db["logs"][-1]
    assert step == "human:payment_gateway_paid"
    assert detail["transaction_id"] == result["transaction_id"]
    assert detail["sandbox"] is True


def test_other_final_approver_cannot_pay(fake_db):
    with pytest.raises(PermissionError):
        db_store.record_gateway_payment(7, successful_result(), "someone_else", actor_role="final_approver")
    assert fake_db["payment"]["payment_status"] == "SCHEDULED"
    assert fake_db["rolled_back"] == 1


def test_finance_officer_can_pay_any(fake_db):
    assert db_store.record_gateway_payment(7, successful_result(), "fin", actor_role="finance_officer")


@pytest.mark.parametrize("role", ["vendor", "department_head", "procurement_officer", ""])
def test_other_roles_cannot_pay(fake_db, role):
    with pytest.raises(PermissionError):
        db_store.record_gateway_payment(7, successful_result(), "fa_user", actor_role=role)


def test_failed_result_cannot_be_recorded(fake_db):
    order = pgw.create_order(scheduled_payment())
    failed = pgw.charge(order, "UPI", {"vpa": "failure@sandbox"})
    with pytest.raises(ValueError):
        db_store.record_gateway_payment(7, failed, "fa_user", actor_role="final_approver")
    assert fake_db["payment"]["payment_status"] == "SCHEDULED"


def test_amount_mismatch_rejected(fake_db):
    result = dict(successful_result(), amount="1.00")
    with pytest.raises(ValueError):
        db_store.record_gateway_payment(7, result, "fa_user", actor_role="final_approver")
    assert fake_db["payment"]["payment_status"] == "SCHEDULED"


def test_result_for_other_payment_rejected(fake_db):
    result = dict(successful_result(), payment_id=999)
    with pytest.raises(ValueError):
        db_store.record_gateway_payment(7, result, "fa_user", actor_role="final_approver")


def test_double_payment_returns_none(fake_db):
    first = db_store.record_gateway_payment(7, successful_result(), "fa_user", actor_role="final_approver")
    second = db_store.record_gateway_payment(7, successful_result(), "fa_user", actor_role="final_approver")
    assert first == "clean_match.pdf"
    assert second is None
    assert sum(1 for step, _ in fake_db["logs"] if step == "human:payment_gateway_paid") == 1
