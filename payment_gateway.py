"""Sandbox payment gateway used after an invoice is fully approved.

This module simulates a hosted payment checkout (UPI, card, net banking).
It never contacts a bank or a real payment provider and never moves money.
It is deliberately free of Streamlit and database imports so it can be
unit-tested on its own.

Sandbox test credentials
------------------------
Card  4111 1111 1111 1111  -> payment succeeds
Card  4000 0000 0000 0002  -> payment is declined by the "issuer"
UPI   success@sandbox (or any valid VPA) -> succeeds
UPI   failure@sandbox      -> payment is declined
Net banking: choose "Sandbox Bank (decline)" to simulate a failure.

Only the last four digits of a card are ever returned for storage or logging.
"""

from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


GATEWAY_NAME = "AP Sandbox Pay"
SANDBOX_NOTICE = (
    "Sandbox mode: no real money moves and no bank is contacted. "
    "The result is recorded as an application payment record only."
)

METHODS = ("UPI", "CARD", "NETBANKING")
METHOD_LABELS = {
    "UPI": "UPI",
    "CARD": "Debit / credit card",
    "NETBANKING": "Net banking",
}

NETBANKING_BANKS = (
    "State Bank of India",
    "HDFC Bank",
    "ICICI Bank",
    "Axis Bank",
    "Punjab National Bank",
    "Sandbox Bank (decline)",
)
_DECLINING_BANKS = {"Sandbox Bank (decline)"}

SUCCESS_TEST_CARD = "4111111111111111"
DECLINE_TEST_CARDS = {"4000000000000002"}
DECLINE_TEST_UPI = {"failure@sandbox"}

_VPA_PATTERN = re.compile(r"^[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9.]{1,63}$")


class PaymentValidationError(ValueError):
    """Raised when the payer's input is incomplete or invalid."""


# --------------------------------------------------
# Orders
# --------------------------------------------------

def _to_amount(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, TypeError, ValueError, AttributeError):
        raise PaymentValidationError("Invalid payment amount.")
    if not amount.is_finite() or amount <= 0:
        raise PaymentValidationError("Payment amount must be greater than zero.")
    return amount.quantize(Decimal("0.01"))


def create_order(payment: dict[str, Any]) -> dict[str, Any]:
    """Build a gateway order from a payment_schedules row."""
    payment_id = payment.get("id")
    if payment_id in (None, ""):
        raise PaymentValidationError("A payment schedule ID is required.")
    status = str(payment.get("payment_status") or "").upper()
    if status != "SCHEDULED":
        raise PaymentValidationError(
            "Only a SCHEDULED payment can be paid (current status: " + (status or "unknown") + ")."
        )

    amount = _to_amount(payment.get("invoice_amount"))
    return {
        "order_id": "order_" + secrets.token_hex(6),
        "payment_id": payment_id,
        "approval_request_id": payment.get("approval_request_id"),
        "invoice_number": str(payment.get("invoice_number") or ""),
        "payee": str(payment.get("vendor_name") or ""),
        "department_id": str(payment.get("department_id") or ""),
        "amount": amount,
        "amount_paise": int(amount * 100),
        "currency": "INR",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# --------------------------------------------------
# Input validation
# --------------------------------------------------

def luhn_valid(number: str) -> bool:
    digits = [int(ch) for ch in number]
    checksum = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _clean_card_number(value: Any) -> str:
    number = re.sub(r"[\s-]", "", str(value or ""))
    if not number.isdigit() or not 12 <= len(number) <= 19:
        raise PaymentValidationError("Enter a valid card number.")
    if not luhn_valid(number):
        raise PaymentValidationError("Card number failed validation. Check the digits.")
    return number


def _check_expiry(value: Any, today: date | None = None) -> None:
    match = re.fullmatch(r"\s*(\d{2})\s*/\s*(\d{2}|\d{4})\s*", str(value or ""))
    if not match:
        raise PaymentValidationError("Enter the expiry as MM/YY.")
    month = int(match.group(1))
    year = int(match.group(2))
    if year < 100:
        year += 2000
    if not 1 <= month <= 12:
        raise PaymentValidationError("Expiry month must be between 01 and 12.")
    today = today or date.today()
    if (year, month) < (today.year, today.month):
        raise PaymentValidationError("This card has expired.")


def validate_details(method: str, details: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Validate payer input and return a safe, storable summary of it."""
    method = str(method or "").upper()
    details = details or {}
    if method not in METHODS:
        raise PaymentValidationError("Choose a payment method.")

    if method == "UPI":
        vpa = str(details.get("vpa") or "").strip().lower()
        if not _VPA_PATTERN.fullmatch(vpa):
            raise PaymentValidationError("Enter a valid UPI ID, for example name@bank.")
        return {"method": method, "display": "UPI · " + vpa, "vpa": vpa}

    if method == "CARD":
        number = _clean_card_number(details.get("card_number"))
        name = str(details.get("name_on_card") or "").strip()
        if len(name) < 2:
            raise PaymentValidationError("Enter the name on the card.")
        _check_expiry(details.get("expiry"), today=today)
        cvv = str(details.get("cvv") or "").strip()
        if not re.fullmatch(r"\d{3,4}", cvv):
            raise PaymentValidationError("Enter a 3 or 4 digit CVV.")
        return {
            "method": method,
            "display": "Card ending " + number[-4:],
            "card_last4": number[-4:],
            # Kept only in memory for the sandbox decision; never stored.
            "_test_outcome": "DECLINE" if number in DECLINE_TEST_CARDS else "APPROVE",
        }

    bank = str(details.get("bank") or "").strip()
    if bank not in NETBANKING_BANKS:
        raise PaymentValidationError("Choose a bank.")
    return {"method": method, "display": "Net banking · " + bank, "bank": bank}


# --------------------------------------------------
# Charge
# --------------------------------------------------

def charge(order: dict[str, Any], method: str, details: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Run a sandbox charge. Returns a result dict; raises only on bad input."""
    if not order or not order.get("order_id"):
        raise PaymentValidationError("The payment order is missing. Reopen the payment window.")

    summary = validate_details(method, details, today=today)
    declined = (
        summary.get("_test_outcome") == "DECLINE"
        or summary.get("vpa") in DECLINE_TEST_UPI
        or summary.get("bank") in _DECLINING_BANKS
    )

    result = {
        "order_id": order["order_id"],
        "payment_id": order.get("payment_id"),
        "amount": str(order.get("amount")),
        "currency": order.get("currency", "INR"),
        "method": summary["method"],
        "method_display": summary["display"],
        "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gateway": GATEWAY_NAME,
        "sandbox": True,
    }
    if summary.get("card_last4"):
        result["card_last4"] = summary["card_last4"]

    if declined:
        result.update({
            "status": "FAILED",
            "transaction_id": None,
            "failure_reason": "Declined by the sandbox issuer (test credentials for a failed payment).",
        })
    else:
        result.update({
            "status": "SUCCESS",
            # Fits payment_schedules.payment_batch_id (VARCHAR 50).
            "transaction_id": "PGW-" + datetime.now(timezone.utc).strftime("%Y%m%d") + "-" + secrets.token_hex(5).upper(),
            "failure_reason": None,
        })
    return result
