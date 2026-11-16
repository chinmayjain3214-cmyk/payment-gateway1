"""Sequential, human-controlled approval workflow backed by PostgreSQL.

All invoices follow the same three stages. No monetary thresholds are inferred.
The legacy ``approver`` role remains an alias for the final approver stage.
"""

from __future__ import annotations

from typing import Any



APPROVAL_STAGES = (
    {
        "stage_key": "DEPARTMENT_HEAD",
        "stage_label": "Department Head",
        "stage_order": 1,
        "required_role": "department_head",
    },
    {
        "stage_key": "FINANCE_OFFICER",
        "stage_label": "Finance Officer",
        "stage_order": 2,
        "required_role": "finance_officer",
    },
    {
        "stage_key": "FINAL_APPROVER",
        "stage_label": "Final Approver",
        "stage_order": 3,
        "required_role": "final_approver",
    },
)

ROLE_ALIASES = {
    "approver": "final_approver",
}

ROLE_LABELS = {
    "department_head": "Department Head",
    "finance_officer": "Finance Officer",
    "final_approver": "Final Approver",
    "approver": "Final Approver",
}


def normalize_approval_role(role: Any) -> str:
    value = str(role or "").strip().lower()
    return ROLE_ALIASES.get(value, value)


def role_can_act(user_role: str, required_role: str) -> bool:
    return normalize_approval_role(user_role) == normalize_approval_role(required_role)


def current_pending_stage(stages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the earliest pending stage, or None when the chain is complete/stopped."""
    ordered = sorted(stages or [], key=lambda item: int(item.get("stage_order") or 0))
    return next((row for row in ordered if str(row.get("status") or "").upper() == "PENDING"), None)


def _ensure_schema(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_workflow_stages (
            request_id INTEGER NOT NULL REFERENCES approval_requests(id) ON DELETE CASCADE,
            stage_key VARCHAR(50) NOT NULL,
            stage_label VARCHAR(80) NOT NULL,
            stage_order INTEGER NOT NULL,
            required_role VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            decided_by VARCHAR(100),
            decided_at TIMESTAMPTZ,
            decision_note TEXT,
            PRIMARY KEY (request_id, stage_key),
            UNIQUE (request_id, stage_order),
            CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED'))
        );
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_workflow_role_status "
        "ON approval_workflow_stages (required_role, status, stage_order);"
    )


def _seed_stages(cur, request_id: int) -> None:
    for stage in APPROVAL_STAGES:
        cur.execute(
            """
            INSERT INTO approval_workflow_stages
                (request_id, stage_key, stage_label, stage_order, required_role, status)
            VALUES (%s, %s, %s, %s, %s, 'PENDING')
            ON CONFLICT (request_id, stage_key) DO NOTHING;
            """,
            (
                request_id,
                stage["stage_key"],
                stage["stage_label"],
                stage["stage_order"],
                stage["required_role"],
            ),
        )


def get_approval_workflow(request_id: int) -> dict[str, Any]:
    """Return stage history and current stage for a request.

    Existing pending requests are lazily enrolled in the three-stage workflow.
    Already-decided legacy requests are not retroactively given fake stage history.
    """
    from db import get_connection

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            _ensure_schema(cur)
            cur.execute(
                "SELECT status FROM approval_requests WHERE id = %s;",
                (request_id,),
            )
            request_row = cur.fetchone()
            if request_row is None:
                raise ValueError("Approval request was not found.")

            request_status = str(request_row[0] or "").upper()
            if request_status == "PENDING":
                _seed_stages(cur, request_id)

            cur.execute(
                """
                SELECT stage_key, stage_label, stage_order, required_role,
                       status, decided_by, decided_at, decision_note
                FROM approval_workflow_stages
                WHERE request_id = %s
                ORDER BY stage_order;
                """,
                (request_id,),
            )
            columns = [
                "stage_key", "stage_label", "stage_order", "required_role",
                "status", "decided_by", "decided_at", "decision_note",
            ]
            stages = [dict(zip(columns, row)) for row in cur.fetchall()]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "request_status": request_status,
        "stages": stages,
        "current_stage": current_pending_stage(stages) if request_status == "PENDING" else None,
    }


def decide_approval_stage(
    request_id: int,
    decision: str,
    decided_by: str,
    user_role: str,
    note: str = "",
) -> dict[str, Any]:
    """Record an approval/rejection for the current stage with row locking.

    Intermediate approvals leave approval_requests.status as PENDING. Only the
    final stage sets it to APPROVED. A rejection at any stage ends the chain.
    """
    decision = str(decision or "").strip().upper()
    if decision not in {"APPROVED", "REJECTED"}:
        raise ValueError("Decision must be APPROVED or REJECTED.")

    decided_by = str(decided_by or "").strip()
    if not decided_by:
        raise ValueError("A reviewer username is required.")

    from db import get_connection

    conn = get_connection()
    audit_event = None
    result: dict[str, Any] | None = None
    try:
        with conn.cursor() as cur:
            _ensure_schema(cur)
            cur.execute(
                "SELECT file_name, status FROM approval_requests WHERE id = %s FOR UPDATE;",
                (request_id,),
            )
            request_row = cur.fetchone()
            if request_row is None:
                raise ValueError("Approval request was not found.")

            file_name, request_status = request_row
            if str(request_status or "").upper() != "PENDING":
                raise ValueError("This invoice is no longer pending approval.")

            _seed_stages(cur, request_id)
            cur.execute(
                """
                SELECT stage_key, stage_label, stage_order, required_role,
                       status, decided_by, decided_at, decision_note
                FROM approval_workflow_stages
                WHERE request_id = %s
                ORDER BY stage_order
                FOR UPDATE;
                """,
                (request_id,),
            )
            columns = [
                "stage_key", "stage_label", "stage_order", "required_role",
                "status", "decided_by", "decided_at", "decision_note",
            ]
            stages = [dict(zip(columns, row)) for row in cur.fetchall()]
            current = current_pending_stage(stages)
            if current is None:
                raise ValueError("No approval stage is currently pending.")
            if not role_can_act(user_role, current["required_role"]):
                raise PermissionError(
                    "This stage requires the " + str(current["stage_label"]) + " role."
                )

            cur.execute(
                """
                UPDATE approval_workflow_stages
                SET status = %s, decided_by = %s, decided_at = CURRENT_TIMESTAMP,
                    decision_note = %s
                WHERE request_id = %s AND stage_key = %s AND status = 'PENDING';
                """,
                (decision, decided_by, str(note or "").strip(), request_id, current["stage_key"]),
            )
            if cur.rowcount != 1:
                raise ValueError("This approval stage was already actioned by another reviewer.")

            if decision == "REJECTED":
                cur.execute(
                    """
                    UPDATE approval_requests
                    SET status = 'REJECTED', decided_by = %s,
                        decided_at = CURRENT_TIMESTAMP, decision_note = %s
                    WHERE id = %s AND status = 'PENDING';
                    """,
                    (decided_by, str(note or "").strip(), request_id),
                )
                result = {
                    "decision": decision,
                    "stage": current["stage_label"],
                    "request_status": "REJECTED",
                    "next_stage": None,
                    "file_name": file_name,
                }
                audit_event = "approval:stage_rejected"
            else:
                next_stage = current_pending_stage(
                    [row for row in stages if row["stage_key"] != current["stage_key"]]
                )
                if next_stage is None:
                    cur.execute(
                        """
                        UPDATE approval_requests
                        SET status = 'APPROVED', decided_by = %s,
                            decided_at = CURRENT_TIMESTAMP, decision_note = %s
                        WHERE id = %s AND status = 'PENDING';
                        """,
                        (decided_by, str(note or "").strip(), request_id),
                    )
                    request_final_status = "APPROVED"
                else:
                    request_final_status = "PENDING"

                result = {
                    "decision": decision,
                    "stage": current["stage_label"],
                    "request_status": request_final_status,
                    "next_stage": next_stage["stage_label"] if next_stage else None,
                    "file_name": file_name,
                }
                audit_event = "approval:stage_approved"

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    audit_recorded = False
    if audit_event and result is not None:
        try:
            from db_store import save_log

            audit_recorded = bool(save_log(
                audit_event,
                {
                    "request_id": request_id,
                    "file": result["file_name"],
                    "stage": result["stage"],
                    "decision": result["decision"],
                    "request_status": result["request_status"],
                    "next_stage": result["next_stage"],
                    "by": decided_by,
                    "role": normalize_approval_role(user_role),
                    "note": str(note or "").strip(),
                },
            ))
        except Exception:
            audit_recorded = False

    if result is not None:
        result["audit_recorded"] = audit_recorded
    return result
