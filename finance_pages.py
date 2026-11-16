"""Preview-only finance workspace for the invoice-agent demo.

Department attribution is intentionally read from the purchase-order / requisition
record, never guessed from the vendor invoice. The data in this module is fictional
UI preview data only. Replace the preview collections with backend service calls
when the PostgreSQL budget and payment APIs are available.
"""

from __future__ import annotations

from typing import Any

import streamlit as st


# ---------------------------------------------------------------------------
# FICTIONAL PREVIEW DATA ONLY.
# No values below represent actual university budgets or payment obligations.
# ---------------------------------------------------------------------------

DEMO_BUDGETS: list[dict[str, Any]] = [
    {
        "department": "Academic Laboratories",
        "cost_center": "ACAD-LAB",
        "allocated": 500_000.00,
        "spent": 180_000.00,
        "committed": 120_000.00,
    },
    {
        "department": "Computer Science",
        "cost_center": "CSE-OPS",
        "allocated": 350_000.00,
        "spent": 205_000.00,
        "committed": 70_000.00,
    },
    {
        "department": "Campus Administration",
        "cost_center": "ADMIN-GEN",
        "allocated": 250_000.00,
        "spent": 90_000.00,
        "committed": 55_000.00,
    },
]

# This is an intentionally unmapped example to show the exception workflow.
# It is not a real invoice or PO and is excluded from all department totals.
DEMO_UNMAPPED_COMMITMENTS: list[dict[str, Any]] = [
    {
        "reference": "DEMO-PO-UNMAPPED-01",
        "vendor": "Example Vendor (fictional)",
        "amount": 8_500.00,
        "department": None,
        "reason": "The PO record has no department / cost-centre mapping.",
        "budget_status": "NOT VERIFIED",
    }
]

# Every scheduled/paid row below is a fictional, already human-approved example.
# Real records must only enter this list from the payment backend after approval.
DEMO_PAYMENTS: list[dict[str, Any]] = [
    {
        "invoice": "DEMO-AP-001",
        "vendor": "Example Lab Supplies",
        "po": "DEMO-PO-001",
        "department": "Academic Laboratories",
        "amount": 5_900.00,
        "invoice_date": "15 Nov 2026",
        "due_date": "18 Nov 2026",
        "terms": "Net 3",
        "status": "DUE SOON",
        "approval_status": "APPROVED",
    },
    {
        "invoice": "DEMO-AP-002",
        "vendor": "Example Electronics",
        "po": "DEMO-PO-002",
        "department": "Computer Science",
        "amount": 30_000.00,
        "invoice_date": "04 Nov 2026",
        "due_date": "10 Nov 2026",
        "terms": "Net 6",
        "status": "OVERDUE",
        "approval_status": "APPROVED",
    },
    {
        "invoice": "DEMO-AP-003",
        "vendor": "Example Campus Services",
        "po": "DEMO-PO-003",
        "department": "Campus Administration",
        "amount": 18_500.00,
        "invoice_date": "15 Nov 2026",
        "due_date": "15 Dec 2026",
        "terms": "Net 30",
        "status": "SCHEDULED",
        "approval_status": "APPROVED",
    },
    {
        "invoice": "DEMO-AP-004",
        "vendor": "Example Office Systems",
        "po": "DEMO-PO-004",
        "department": "Campus Administration",
        "amount": 12_750.00,
        "invoice_date": "01 Nov 2026",
        "due_date": "08 Nov 2026",
        "terms": "Net 7",
        "status": "PAID",
        "approval_status": "APPROVED",
    },
]

# An unmapped department example is deliberately NOT a payment-schedule row.
# It must be resolved and approved before it can be scheduled.
DEMO_BLOCKED_FROM_SCHEDULING: list[dict[str, Any]] = [
    {
        "invoice": "DEMO-UNASSIGNED-01",
        "vendor": "Example Vendor (fictional)",
        "po": "DEMO-PO-UNMAPPED-01",
        "amount": 8_500.00,
        "reason": "Department is missing from the PO master record.",
        "status": "NOT SCHEDULED",
    }
]


def _money(value: Any) -> str:
    try:
        return f"₹{float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _budget_rows() -> list[dict[str, Any]]:
    """Calculate display-only totals for the fictional preview budgets."""
    rows: list[dict[str, Any]] = []
    for record in DEMO_BUDGETS:
        allocated = float(record["allocated"])
        spent = float(record["spent"])
        committed = float(record["committed"])
        available = allocated - spent - committed
        utilization = ((spent + committed) / allocated * 100) if allocated > 0 else 0.0
        rows.append(
            {
                **record,
                "available": available,
                "utilization": utilization,
                "mapping_status": "MAPPED",
            }
        )
    return rows


def _status_text(status: str) -> str:
    return str(status or "UNKNOWN").upper()


def _render_department_mapping_exceptions() -> None:
    st.markdown("### Department mapping exceptions")
    st.caption(
        "Unmapped records are kept separate from department budget totals. "
        "Their budget status is NOT VERIFIED until an authorized user resolves the mapping."
    )

    if not DEMO_UNMAPPED_COMMITMENTS:
        st.success("No unmapped department commitments in this preview.")
        return

    st.warning(
        f"{len(DEMO_UNMAPPED_COMMITMENTS)} illustrative record(s) have no department mapping. "
        "These amounts are excluded from the department totals above."
    )

    st.dataframe(
        [
            {
                "PO / reference": row["reference"],
                "Vendor": row["vendor"],
                "Department": "UNASSIGNED",
                "Amount": _money(row["amount"]),
                "Budget status": row["budget_status"],
                "Reason": row["reason"],
            }
            for row in DEMO_UNMAPPED_COMMITMENTS
        ],
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("How an unmapped department is handled"):
        st.markdown(
            "1. Read the PO number from the invoice.\n"
            "2. Look up that PO in the university procurement records.\n"
            "3. Read the department / cost centre from the PO or linked requisition.\n"
            "4. If the mapping is missing, show **UNASSIGNED** and **NOT VERIFIED**.\n"
            "5. Route the exception to Procurement / Finance for an authorized correction.\n\n"
            "The system must not infer a department from the vendor name, item description, "
            "or invoice text. The unmapped amount must not be silently charged to a default department."
        )


def render_budget_overview() -> None:
    st.markdown("### Department budget overview")
    st.info(
        "Preview mode — all amounts and department names below are fictional examples. "
        "They are not live university balances and cannot authorize spending."
    )
    st.markdown(
        "**Where does the department come from?** The vendor invoice does not need to "
        "contain a department. The system obtains the department / cost centre from the "
        "matched PO or linked purchase requisition."
    )

    rows = _budget_rows()
    total_allocated = sum(row["allocated"] for row in rows)
    total_spent = sum(row["spent"] for row in rows)
    total_committed = sum(row["committed"] for row in rows)
    total_available = sum(row["available"] for row in rows)
    unassigned_count = len(DEMO_UNMAPPED_COMMITMENTS)
    unassigned_amount = sum(float(row["amount"]) for row in DEMO_UNMAPPED_COMMITMENTS)

    metric_cols = st.columns(5)
    metric_cols[0].metric("Total allocated", _money(total_allocated))
    metric_cols[1].metric("Spent", _money(total_spent))
    metric_cols[2].metric("Committed", _money(total_committed))
    metric_cols[3].metric("Available", _money(total_available))
    metric_cols[4].metric("Unassigned records", unassigned_count)

    st.caption(
        "Available = allocated − spent − committed. Unassigned records are excluded "
        "from these department totals until their PO / requisition mapping is resolved. "
        f"Illustrative unassigned amount: {_money(unassigned_amount)}."
    )
    st.divider()

    departments = ["All departments"] + [row["department"] for row in rows]
    selected = st.selectbox(
        "Filter by department",
        departments,
        key="finance_budget_department_filter",
    )
    visible = rows if selected == "All departments" else [
        row for row in rows if row["department"] == selected
    ]

    st.dataframe(
        [
            {
                "Department": row["department"],
                "Cost centre": row["cost_center"],
                "Mapping": row["mapping_status"],
                "Allocated": _money(row["allocated"]),
                "Spent": _money(row["spent"]),
                "Committed": _money(row["committed"]),
                "Available": _money(row["available"]),
                "Utilization": f"{row['utilization']:.1f}%",
            }
            for row in visible
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### Budget utilization")
    for row in visible:
        st.markdown(
            f"**{row['department']}** · {row['utilization']:.1f}% used or committed"
        )
        st.progress(min(max(row["utilization"] / 100.0, 0.0), 1.0))
        if row["available"] < 0:
            st.error("Illustrative budget exceeded")
        elif row["available"] <= row["allocated"] * 0.1:
            st.warning("Illustrative remaining balance is low")

    st.divider()
    _render_department_mapping_exceptions()
    st.caption(
        "Backend connection pending: live PO-to-department mapping, budget reservations, "
        "actual expenditure, and balance updates will come from the PostgreSQL backend."
    )


def _render_blocked_scheduling_examples() -> None:
    st.markdown("### Not eligible for scheduling")
    st.caption(
        "These illustrative records are intentionally excluded from the payment schedule. "
        "An invoice must be human-approved and have its required procurement / budget checks resolved first."
    )

    if not DEMO_BLOCKED_FROM_SCHEDULING:
        st.success("No blocked examples in this preview.")
        return

    st.warning(
        "A missing department mapping means the budget cannot be verified. "
        "The record stays out of the payment schedule until the mapping is resolved and approval is complete."
    )
    st.dataframe(
        [
            {
                "Invoice": row["invoice"],
                "Vendor": row["vendor"],
                "PO": row["po"],
                "Department": "UNASSIGNED",
                "Amount": _money(row["amount"]),
                "Payment status": row["status"],
                "Reason": row["reason"],
            }
            for row in DEMO_BLOCKED_FROM_SCHEDULING
        ],
        use_container_width=True,
        hide_index=True,
    )


def render_payment_schedule() -> None:
    st.markdown("### Payment schedule")
    st.info(
        "Preview mode — all payment rows are fictional examples of invoices that have "
        "already received human approval. No payment has been scheduled, sent, or marked as paid by this screen."
    )

    rows = [row for row in DEMO_PAYMENTS if row.get("approval_status") == "APPROVED"]
    statuses = ("SCHEDULED", "DUE SOON", "OVERDUE", "PAID")
    status_counts = {
        status: sum(1 for row in rows if row["status"] == status)
        for status in statuses
    }
    unpaid_total = sum(float(row["amount"]) for row in rows if row["status"] != "PAID")

    metrics = st.columns(5)
    metrics[0].metric("Scheduled", status_counts["SCHEDULED"])
    metrics[1].metric("Due soon", status_counts["DUE SOON"])
    metrics[2].metric("Overdue", status_counts["OVERDUE"])
    metrics[3].metric("Paid", status_counts["PAID"])
    metrics[4].metric("Unpaid total", _money(unpaid_total))

    st.divider()
    selected_status = st.selectbox(
        "Filter payment status",
        ["All statuses", *statuses],
        key="finance_payment_status_filter",
    )
    search = st.text_input(
        "Search payments",
        placeholder="Invoice number, vendor, PO, or department...",
        key="finance_payment_search",
    ).strip().casefold()

    visible = []
    for row in rows:
        if selected_status != "All statuses" and row["status"] != selected_status:
            continue
        searchable = " ".join(
            str(row.get(key, ""))
            for key in ("invoice", "vendor", "po", "department")
        ).casefold()
        if search and search not in searchable:
            continue
        visible.append(row)

    st.caption(f"Showing {len(visible)} of {len(rows)} illustrative approved payment records.")
    if visible:
        st.dataframe(
            [
                {
                    "Invoice": row["invoice"],
                    "Vendor": row["vendor"],
                    "PO": row["po"],
                    "Department (from PO)": row["department"] or "UNASSIGNED",
                    "Amount": _money(row["amount"]),
                    "Invoice date": row["invoice_date"],
                    "Due date": row["due_date"],
                    "Terms": row["terms"],
                    "Status": _status_text(row["status"]),
                }
                for row in visible
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No illustrative approved payments match the selected filters.")

    st.divider()
    _render_blocked_scheduling_examples()

    st.divider()
    st.markdown("### Payment record actions")
    st.caption(
        "Actions will be enabled after the payment API and audit trail are connected. "
        "A payment can only be marked paid after Finance confirms settlement."
    )
    st.button(
        "Mark as paid (backend connection required)",
        disabled=True,
        help="Disabled in preview mode so this screen cannot change payment status.",
    )


def render_finance_page(user: dict[str, Any]) -> None:
    """Render the preview-only finance workspace for administrators."""
    role = str(user.get("role") or "").strip().lower()
    if role != "admin":
        st.error("You do not have permission to open the finance workspace.")
        return

    st.markdown(
        "<div class='page-eyebrow'>FINANCE OPERATIONS</div>",
        unsafe_allow_html=True,
    )
    st.title("Finance workspace")
    st.caption(
        "Review department budget utilization, resolve missing department mappings, "
        "and track approved invoice payment timelines."
    )

    budget_tab, payment_tab = st.tabs(["Budget overview", "Payment schedule"])
    with budget_tab:
        render_budget_overview()
    with payment_tab:
        render_payment_schedule()
