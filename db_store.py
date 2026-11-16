
import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from db import get_connection


# Local recovery storage.
BASE_DIR = Path(__file__).resolve().parent
RECOVERY_DIR = BASE_DIR / "data" / "recovery" / "approval_requests"


# ==================================================
# 1. AUDIT LOGGING
# ==================================================

def save_log(step, detail):
    """Write one agent step to PostgreSQL. Return True if successful."""

    conn = None

    try:
        conn = get_connection()

        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_log (step, detail) VALUES (%s, %s);",
                (
                    step,
                    json.dumps(
                        detail,
                        ensure_ascii=False,
                        default=str
                    ),
                ),
            )

        conn.commit()
        return True

    except Exception as e:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass

        print(
            "  [warning] Could not save audit log:",
            str(e)[:120]
        )
        return False

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ==================================================
# 2. LOCAL APPROVAL RECOVERY
# ==================================================

def _recovery_file(file_name):
    """Return a safe, stable local recovery filename."""

    key = hashlib.sha256(
        str(file_name).encode("utf-8")
    ).hexdigest()

    return RECOVERY_DIR / (key + ".json")


def has_queued_approval_request(file_name):
    """Check whether an approval request is waiting for database recovery."""

    try:
        return _recovery_file(file_name).is_file()
    except OSError:
        return False


def _queue_approval_request(
    file_name,
    recommendation,
    summary,
    review_reason
):
    """Atomically preserve an approval request on local disk."""

    temporary_path = None

    try:
        RECOVERY_DIR.mkdir(parents=True, exist_ok=True)

        payload = {
            "version": 1,
            "file_name": str(file_name),
            "recommendation": str(recommendation),
            "summary": summary,
            "review_reason": review_reason,
            "queued_at": datetime.now().astimezone().isoformat(),
        }

        destination = _recovery_file(file_name)

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=RECOVERY_DIR,
            prefix="approval_",
            suffix=".tmp",
            delete=False,
        ) as temp_file:

            temporary_path = Path(temp_file.name)

            json.dump(
                payload,
                temp_file,
                indent=2,
                ensure_ascii=False,
                default=str,
            )

            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.replace(temporary_path, destination)

        print(
            "  [recovery] Approval request saved locally:",
            file_name
        )

        return True

    except Exception as e:
        print(
            "  [critical warning] Could not save approval request "
            "to local recovery storage:",
            str(e)[:150]
        )
        return False

    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _remove_recovery_file(file_name):
    """Remove a recovery record after successful database saving."""

    try:
        _recovery_file(file_name).unlink(missing_ok=True)
    except OSError as e:
        print(
            "  [warning] Could not remove recovered request file:",
            str(e)[:120]
        )


# ==================================================
# 3. DATABASE APPROVAL SAVING
# ==================================================

def _save_approval_request_to_database(
    file_name,
    recommendation,
    summary,
    review_reason
):
    """
    Save one approval request.

    A PostgreSQL transaction-level advisory lock prevents concurrent
    calls using this function from inserting duplicate pending rows
    for the same filename.
    """

    conn = None

    try:
        conn = get_connection()

        with conn.cursor() as cur:

            # Serialize saves for the same invoice filename.
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s), 0);",
                (str(file_name),),
            )

            # Update an existing pending request.
            cur.execute(
                """
                UPDATE approval_requests
                SET
                    recommendation = %s,
                    summary = %s,
                    review_reason = %s,
                    created_at = CURRENT_TIMESTAMP
                WHERE file_name = %s
                  AND status = 'PENDING'
                RETURNING id;
                """,
                (
                    recommendation,
                    summary,
                    review_reason,
                    file_name,
                ),
            )

            row = cur.fetchone()

            # Insert if no pending request exists.
            if row is None:
                cur.execute(
                    """
                    INSERT INTO approval_requests
                    (
                        file_name,
                        recommendation,
                        summary,
                        review_reason
                    )
                    VALUES (%s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        file_name,
                        recommendation,
                        summary,
                        review_reason,
                    ),
                )

                row = cur.fetchone()

        conn.commit()

        if row is None:
            raise RuntimeError(
                "Database did not return an approval request ID."
            )

        return row[0]

    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass

        raise

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def save_approval_request(
    file_name,
    recommendation,
    summary,
    review_reason
):
    """
    Save an approval request to PostgreSQL.

    If PostgreSQL is unavailable, preserve the request locally.
    Returns the database request ID, or None if it was queued locally
    or could not be saved.
    """

    try:
        request_id = _save_approval_request_to_database(
            file_name,
            recommendation,
            summary,
            review_reason,
        )

        # Remove any older recovery copy after successful saving.
        _remove_recovery_file(file_name)

        return request_id

    except Exception as e:

        print(
            "  [warning] PostgreSQL approval save failed:",
            str(e)[:150]
        )

        queued = _queue_approval_request(
            file_name,
            recommendation,
            summary,
            review_reason,
        )

        if not queued:
            print(
                "  [critical] Approval request could not be "
                "saved in PostgreSQL or local recovery storage."
            )

        return None


# ==================================================
# 4. RECOVER PENDING APPROVAL REQUESTS
# ==================================================

def sync_pending_approval_requests():
    """
    Retry locally queued approval requests.

    Successful records are removed from the recovery directory.
    Failed records remain available for another recovery attempt.
    """

    result = {
        "synced": 0,
        "remaining": 0,
        "errors": [],
    }

    if not RECOVERY_DIR.is_dir():
        return result

    try:
        recovery_files = sorted(
            RECOVERY_DIR.glob("*.json")
        )
    except OSError as e:
        result["errors"].append(str(e)[:150])
        return result

    for recovery_file in recovery_files:

        try:
            payload = json.loads(
                recovery_file.read_text(encoding="utf-8")
            )

            if not isinstance(payload, dict):
                raise ValueError("Invalid recovery record.")

            file_name = payload.get("file_name")
            recommendation = payload.get("recommendation")

            if not file_name:
                raise ValueError("Recovery record has no filename.")

            if recommendation not in (
                "READY_FOR_APPROVAL",
                "NEEDS_HUMAN_REVIEW",
            ):
                raise ValueError("Invalid approval recommendation.")

            request_id = _save_approval_request_to_database(
                file_name,
                recommendation,
                payload.get("summary"),
                payload.get("review_reason"),
            )

            if request_id is None:
                raise RuntimeError("No database request ID returned.")

            _remove_recovery_file(file_name)

            result["synced"] += 1

            print(
                "  [recovery] Successfully synchronized:",
                file_name
            )

        except Exception as e:

            result["errors"].append(
                str(recovery_file.name) + ": " + str(e)[:150]
            )

            # Stop retrying additional records while the database
            # appears unavailable. Leave every remaining file intact.
            break

    try:
        result["remaining"] = len(
            list(RECOVERY_DIR.glob("*.json"))
        )
    except OSError:
        result["remaining"] = -1

    if result["synced"]:
        print(
            "  [recovery] Synchronized",
            result["synced"],
            "approval request(s)."
        )

    return result


# ==================================================
# 5. APPROVAL REQUEST RETRIEVAL
# ==================================================

REQUEST_COLUMNS = [
    "id",
    "file_name",
    "recommendation",
    "summary",
    "review_reason",
    "status",
    "created_at",
    "decided_by",
    "decided_at",
    "decision_note",
]


def list_approval_requests(status=None):
    """
    Return approval requests, newest first.

    Automatically attempts to recover locally queued requests first.
    """

    recovery_result = sync_pending_approval_requests()

    if recovery_result["remaining"]:
        print(
            "  [recovery] Pending local requests:",
            recovery_result["remaining"]
        )

    conn = get_connection()

    try:
        with conn.cursor() as cur:

            sql = (
                "SELECT "
                + ", ".join(REQUEST_COLUMNS)
                + " FROM approval_requests"
            )

            params = ()

            if status:
                sql += " WHERE status = %s"
                params = (status,)

            sql += " ORDER BY created_at DESC, id DESC;"

            cur.execute(sql, params)
            rows = cur.fetchall()

        return [
            dict(zip(REQUEST_COLUMNS, row))
            for row in rows
        ]

    finally:
        conn.close()


# ==================================================
# 6. HUMAN APPROVAL AND REJECTION
# ==================================================


def _auto_create_payment_schedule(approval_request_id, invoice_number):
    """Create a payment schedule only from complete, verified invoice data."""
    import json
    from decimal import Decimal, InvalidOperation
    from datetime import date, timedelta

    invoice_file = str(invoice_number or "").strip()
    if not invoice_file or Path(invoice_file).name != invoice_file:
        raise ValueError("Invalid invoice reference for payment scheduling.")

    extracted_path = BASE_DIR / "data" / "invoices" / (invoice_file + ".json")
    if not extracted_path.is_file():
        raise FileNotFoundError("Extracted invoice data was not found: " + invoice_file)

    data = json.loads(extracted_path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "_cache_version" in data:
        data = data.get("data", {})
    if not isinstance(data, dict):
        raise ValueError("Invoice extraction data is invalid.")

    raw_amount = (
        data.get("total_amount")
        or data.get("total")
        or data.get("grand_total")
        or data.get("invoice_total")
        or data.get("amount_due")
    )
    try:
        amount = Decimal(str(raw_amount).replace(",", "").replace("₹", "").replace("$", "").strip())
    except (InvalidOperation, TypeError, ValueError, AttributeError):
        raise ValueError("Invoice has no valid total amount.")
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Invoice amount must be greater than zero.")

    vendor_value = data.get("vendor") or data.get("vendor_name")
    if isinstance(vendor_value, dict):
        vendor_value = (
            vendor_value.get("name")
            or vendor_value.get("vendor_name")
            or vendor_value.get("supplier_name")
        )
    vendor_name = str(vendor_value or "").replace("\r", "\n").split("\n", 1)[0].strip()
    if not vendor_name:
        raise ValueError("Invoice vendor name is missing.")

    po_ref = data.get("po_number") or data.get("po_reference") or data.get("purchase_order")
    if not po_ref:
        raise ValueError("Invoice PO reference is missing.")

    from tools import find_po
    po_result = find_po(po_ref)
    if not isinstance(po_result, dict) or po_result.get("status") != "found":
        raise ValueError("Purchase order could not be verified for payment scheduling.")
    po = po_result.get("po") or {}
    department_id = po.get("department_id")
    if not department_id:
        raise ValueError("The purchase order has no department assigned.")

    return create_payment_schedule(
        approval_request_id=approval_request_id,
        invoice_amount=amount,
        scheduled_payment_date=date.today() + timedelta(days=30),
        vendor_name=vendor_name,
        invoice_number=invoice_file,
        department_id=department_id,
    )


def decide_request(request_id, decision, decided_by, note):
    """Record a legacy single-stage decision for a pending request."""
    if decision not in ("APPROVED", "REJECTED"):
        raise ValueError("decision must be APPROVED or REJECTED")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE approval_requests
                SET status = %s,
                    decided_by = %s,
                    decided_at = CURRENT_TIMESTAMP,
                    decision_note = %s
                WHERE id = %s AND status = 'PENDING'
                RETURNING file_name;
                """,
                (decision, decided_by, note, request_id),
            )
            row = cur.fetchone()
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    if row is None:
        return None

    invoice_number = row[0]
    save_log(
        "human:" + decision.lower(),
        {
            "request_id": request_id,
            "file": invoice_number,
            "by": decided_by,
            "note": note,
        },
    )

    if decision == "APPROVED":
        try:
            _auto_create_payment_schedule(request_id, invoice_number)
        except Exception as exc:
            # The human decision remains saved; payment scheduling can be retried.
            print("  [warning] Could not create payment schedule:", str(exc)[:150])

    return invoice_number


# ==================================================
# 7. PAYMENT SCHEDULES
# ==================================================

PAYMENT_COLUMNS = [
    "id",
    "approval_request_id",
    "vendor_name",
    "invoice_number",
    "department_id",
    "invoice_amount",
    "scheduled_payment_date",
    "payment_status",
    "payment_batch_id",
    "paid_at",
    "paid_by",
    "created_at",
]


def create_payment_schedule(
    approval_request_id,
    invoice_amount,
    scheduled_payment_date,
    *,
    vendor_name=None,
    invoice_number=None,
    department_id=None,
):
    """Create one schedule only for a fully approved request; safe to retry."""
    from datetime import date, datetime
    from decimal import Decimal, InvalidOperation

    try:
        amount = Decimal(str(invoice_amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid payment amount.")
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Payment amount must be greater than zero.")

    vendor_name = str(vendor_name or "").strip()
    invoice_number = str(invoice_number or "").strip()
    department_id = str(department_id or "").strip()
    if not vendor_name:
        raise ValueError("Vendor name is required.")
    if not invoice_number:
        raise ValueError("Invoice number is required.")
    if not department_id:
        raise ValueError("Department is required.")

    if isinstance(scheduled_payment_date, datetime):
        scheduled_payment_date = scheduled_payment_date.date()
    elif isinstance(scheduled_payment_date, str):
        try:
            scheduled_payment_date = date.fromisoformat(scheduled_payment_date)
        except ValueError:
            raise ValueError("Invalid scheduled payment date.")
    if not isinstance(scheduled_payment_date, date):
        raise ValueError("A valid scheduled payment date is required.")

    conn = get_connection()
    created = False
    try:
        with conn.cursor() as cur:
            # Lock the request row so concurrent attempts cannot race approval status.
            cur.execute(
                "SELECT status FROM approval_requests WHERE id = %s FOR UPDATE;",
                (approval_request_id,),
            )
            request_row = cur.fetchone()
            if request_row is None:
                raise ValueError("Approval request does not exist.")
            if str(request_row[0]).upper() != "APPROVED":
                raise PermissionError(
                    "A payment schedule can only be created for a fully approved invoice."
                )

            cur.execute(
                "SELECT id FROM payment_schedules WHERE approval_request_id = %s FOR UPDATE;",
                (approval_request_id,),
            )
            existing = cur.fetchone()
            if existing is not None:
                payment_id = existing[0]
            else:
                cur.execute(
                    """
                    INSERT INTO payment_schedules
                    (
                        approval_request_id, vendor_name, invoice_number,
                        department_id, invoice_amount, scheduled_payment_date
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        approval_request_id, vendor_name, invoice_number,
                        department_id, amount, scheduled_payment_date,
                    ),
                )
                inserted = cur.fetchone()
                if inserted is None:
                    raise RuntimeError("Payment schedule was not created.")
                payment_id = inserted[0]
                created = True
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    if created:
        save_log(
            "system:payment_scheduled",
            {
                "payment_id": payment_id,
                "approval_request_id": approval_request_id,
                "invoice": invoice_number,
                "amount": str(amount),
                "department_id": department_id,
            },
        )
    return payment_id


def list_payment_schedules(status=None):
    """Return payment schedules, optionally filtered by status."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            sql = "SELECT " + ", ".join(PAYMENT_COLUMNS) + " FROM payment_schedules"
            params = ()
            if status:
                sql += " WHERE payment_status = %s"
                params = (status,)
            sql += " ORDER BY scheduled_payment_date ASC, id ASC;"
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [dict(zip(PAYMENT_COLUMNS, row)) for row in rows]
    finally:
        conn.close()


def _require_payment_operator(actor_role):
    role = str(actor_role or "").strip().lower()
    if role not in {"finance_officer", "admin"}:
        raise PermissionError("Only Finance Officers or Admins can process payments.")


def mark_payment_paid(payment_id, paid_by, batch_id=None, *, actor_role=None):
    """Mark a scheduled payment as paid; does not initiate a bank transfer."""
    _require_payment_operator(actor_role)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE payment_schedules
                SET payment_status = 'PAID', paid_at = CURRENT_TIMESTAMP,
                    paid_by = %s, payment_batch_id = %s
                WHERE id = %s AND payment_status = 'SCHEDULED'
                RETURNING invoice_number, approval_request_id;
                """,
                (paid_by, batch_id, payment_id),
            )
            row = cur.fetchone()
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    if row is None:
        return None
    invoice_number, approval_request_id = row
    save_log(
        "human:payment_paid",
        {
            "payment_id": payment_id,
            "invoice": invoice_number,
            "approval_request_id": approval_request_id,
            "by": paid_by,
            "batch_id": batch_id,
        },
    )
    return invoice_number


GATEWAY_PAYER_ROLES = {"finance_officer", "admin", "final_approver", "approver"}


def get_payment_schedule(payment_id=None, *, approval_request_id=None):
    """Return one payment schedule row as a dict, or None."""
    if payment_id is None and approval_request_id is None:
        raise ValueError("A payment ID or approval request ID is required.")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            sql = "SELECT " + ", ".join(PAYMENT_COLUMNS) + " FROM payment_schedules WHERE "
            if payment_id is not None:
                cur.execute(sql + "id = %s;", (payment_id,))
            else:
                cur.execute(sql + "approval_request_id = %s;", (approval_request_id,))
            row = cur.fetchone()
        return dict(zip(PAYMENT_COLUMNS, row)) if row else None
    finally:
        conn.close()


def _final_approver_of(cur, approval_request_id):
    """Username who gave the final approval for a request, if recorded."""
    cur.execute("SELECT to_regclass('approval_workflow_stages');")
    if cur.fetchone()[0] is not None:
        cur.execute(
            """
            SELECT decided_by FROM approval_workflow_stages
            WHERE request_id = %s AND stage_key = 'FINAL_APPROVER' AND status = 'APPROVED';
            """,
            (approval_request_id,),
        )
        row = cur.fetchone()
        if row and row[0]:
            return str(row[0])
    cur.execute(
        "SELECT decided_by FROM approval_requests WHERE id = %s AND status = 'APPROVED';",
        (approval_request_id,),
    )
    row = cur.fetchone()
    return str(row[0]) if row and row[0] else None


def can_pay_through_gateway(payment, username, actor_role):
    """UI helper: may this user open the payment window for this schedule?"""
    role = str(actor_role or "").strip().lower()
    if role not in GATEWAY_PAYER_ROLES or not payment:
        return False
    if role in {"finance_officer", "admin"}:
        return True
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            return _final_approver_of(cur, payment["approval_request_id"]) == str(username)
    finally:
        conn.close()


def record_gateway_payment(payment_id, gateway_result, paid_by, *, actor_role=None):
    """Record a successful sandbox gateway charge against a scheduled payment.

    Finance Officers and Admins may pay any scheduled entry. A Final Approver
    may pay only an invoice whose final approval they personally gave.
    Returns the invoice number, or None if the entry was already processed.
    """
    from decimal import Decimal, InvalidOperation

    role = str(actor_role or "").strip().lower()
    if role not in GATEWAY_PAYER_ROLES:
        raise PermissionError("Only Final Approvers, Finance Officers or Admins can pay invoices.")

    result = gateway_result or {}
    if str(result.get("status") or "").upper() != "SUCCESS":
        raise ValueError("Only a successful gateway result can be recorded as paid.")
    transaction_id = str(result.get("transaction_id") or "").strip()
    if not transaction_id or len(transaction_id) > 50:
        raise ValueError("The gateway did not return a valid transaction ID.")
    if str(result.get("payment_id")) != str(payment_id):
        raise ValueError("The gateway result does not belong to this payment.")
    try:
        charged = Decimal(str(result.get("amount")))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("The gateway result has no valid amount.")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT approval_request_id, invoice_amount
                FROM payment_schedules WHERE id = %s FOR UPDATE;
                """,
                (payment_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("Payment schedule was not found.")
            approval_request_id, amount = row

            if role in {"final_approver", "approver"}:
                if _final_approver_of(cur, approval_request_id) != str(paid_by):
                    raise PermissionError(
                        "Only the Final Approver who approved this invoice can pay it."
                    )

            if charged != Decimal(str(amount)):
                raise ValueError("The charged amount does not match the scheduled amount.")

            cur.execute(
                """
                UPDATE payment_schedules
                SET payment_status = 'PAID', paid_at = CURRENT_TIMESTAMP,
                    paid_by = %s, payment_batch_id = %s
                WHERE id = %s AND payment_status = 'SCHEDULED'
                RETURNING invoice_number;
                """,
                (paid_by, transaction_id, payment_id),
            )
            updated = cur.fetchone()
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    if updated is None:
        return None
    save_log(
        "human:payment_gateway_paid",
        {
            "payment_id": payment_id,
            "invoice": updated[0],
            "approval_request_id": approval_request_id,
            "by": paid_by,
            "role": role,
            "transaction_id": transaction_id,
            "order_id": result.get("order_id"),
            "method": result.get("method_display"),
            "amount": result.get("amount"),
            "gateway": result.get("gateway"),
            "sandbox": bool(result.get("sandbox")),
        },
    )
    return updated[0]


def log_gateway_failure(payment_id, gateway_result, attempted_by):
    """Audit a declined gateway attempt. The schedule stays SCHEDULED."""
    result = gateway_result or {}
    return save_log(
        "human:payment_gateway_failed",
        {
            "payment_id": payment_id,
            "by": attempted_by,
            "order_id": result.get("order_id"),
            "method": result.get("method_display"),
            "amount": result.get("amount"),
            "reason": result.get("failure_reason"),
            "sandbox": bool(result.get("sandbox")),
        },
    )


def cancel_payment(payment_id, cancelled_by, *, actor_role=None):
    """Cancel a scheduled payment that has not yet been processed."""
    _require_payment_operator(actor_role)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE payment_schedules
                SET payment_status = 'CANCELLED'
                WHERE id = %s AND payment_status = 'SCHEDULED'
                RETURNING invoice_number;
                """,
                (payment_id,),
            )
            row = cur.fetchone()
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    if row is None:
        return None
    save_log(
        "human:payment_cancelled",
        {"payment_id": payment_id, "invoice": row[0], "by": cancelled_by},
    )
    return row[0]

# ==================================================
# 8. VENDOR CLARIFICATION MESSAGES
# ==================================================

def set_vendor_message(file_name, message):
    """
    Attach a vendor-facing clarification message to the newest
    PENDING approval request for this invoice.

    Returns the request id, or None if no pending request exists.
    """

    if not message:
        return None

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE approval_requests
                SET vendor_message = %s
                WHERE id = (
                    SELECT id FROM approval_requests
                    WHERE file_name = %s
                      AND status = 'PENDING'
                    ORDER BY id DESC
                    LIMIT 1
                )
                RETURNING id;
                """,
                (str(message)[:2000], file_name),
            )

            row = cur.fetchone()

        conn.commit()

        if row is None:
            return None

        save_log(
            "vendor:clarification_sent",
            {
                "file": file_name,
                "request_id": row[0],
                "message": str(message)[:200],
            },
        )

        return row[0]

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise

    finally:
        conn.close()


def list_vendor_submissions(vendor_username, limit=50):
    """
    Return the newest N approval requests for uploads made by this vendor.

    Since approval_requests does not carry a vendor column, we match
    on the `vendor:upload` audit event: it stores the uploader's
    username and the resulting file_name.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            # Find file_names this vendor has uploaded.
            cur.execute(
                """
                SELECT DISTINCT detail->>'file' AS file_name
                FROM agent_log
                WHERE step = 'vendor:upload'
                  AND detail->>'user' = %s
                  AND detail->>'file' IS NOT NULL;
                """,
                (vendor_username,),
            )
            filenames = [row[0] for row in cur.fetchall() if row[0]]

            if not filenames:
                return []

            cur.execute(
                """
                SELECT
                    id,
                    file_name,
                    recommendation,
                    summary,
                    review_reason,
                    vendor_message,
                    status,
                    created_at,
                    decided_by,
                    decided_at,
                    decision_note
                FROM approval_requests
                WHERE file_name = ANY(%s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s;
                """,
                (filenames, limit),
            )

            columns = [
                "id", "file_name", "recommendation", "summary",
                "review_reason", "vendor_message", "status",
                "created_at", "decided_by", "decided_at",
                "decision_note",
            ]

            return [dict(zip(columns, row)) for row in cur.fetchall()]

    finally:
        conn.close()


def acknowledge_vendor_message(request_id):
    """
    Clear the vendor_message after the vendor has acknowledged it.

    Leaves the approval request unchanged otherwise.
    Returns True if a row was updated.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE approval_requests
                SET vendor_message = NULL
                WHERE id = %s
                  AND vendor_message IS NOT NULL
                RETURNING id;
                """,
                (request_id,),
            )

            row = cur.fetchone()

        conn.commit()

        return row is not None

    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise

    finally:
        conn.close()
