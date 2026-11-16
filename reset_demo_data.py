"""Clear data left by earlier test runs so a demo starts clean.

Removes:
- approval requests, approval stages, payment schedules and the activity log
  (PostgreSQL tables approval_requests, approval_workflow_stages,
  payment_schedules, agent_log)
- uploaded invoice copies the app saved in invoices/upload_*
  (your original files in demo_test_invoices/ and invoices/ are untouched)
- the UI-test fixtures for PO-117 / GRN-117 and the SUP-117 test reading

Keeps: user accounts, seeded vendors / POs / GRNs, the reference dataset,
the PO-130..137 demo fixtures and all other saved readings.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

from db import get_connection  # noqa: E402  (needs .env loaded first)

TABLES = [
    "approval_workflow_stages",
    "payment_schedules",
    "approval_requests",
    "agent_log",
]

TEST_FILES = [
    "data/purchase_orders/po_117.json",
    "data/goods_receipts/grn_117.json",
    "data/invoices/upload_754a6383331488ae1ce681f67e430e057fbdadc4d1889c0eb993597335906bb0.pdf.json",
]


def clear_tables() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            existing = []
            for table in TABLES:
                cur.execute("SELECT to_regclass(%s);", (table,))
                if cur.fetchone()[0] is not None:
                    cur.execute("SELECT COUNT(*) FROM " + table + ";")
                    print("  " + table + ": " + str(cur.fetchone()[0]) + " row(s) removed")
                    existing.append(table)
            if existing:
                cur.execute(
                    "TRUNCATE TABLE " + ", ".join(existing) + " RESTART IDENTITY CASCADE;"
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def remove_file(path: Path) -> None:
    try:
        path.unlink()
        print("  removed " + str(path.relative_to(HERE)))
    except FileNotFoundError:
        pass


def main() -> int:
    print("Clearing demo data")
    print("==================")
    print("Database:")
    try:
        clear_tables()
    except Exception as exc:
        print("[FAIL] Could not clear the database: " + str(exc)[:200])
        return 1

    print("Files:")
    for path in sorted((HERE / "invoices").glob("upload_*")):
        if path.is_file():
            remove_file(path)
    for relative in TEST_FILES:
        remove_file(HERE / relative)
    recovery = HERE / "data" / "recovery" / "approval_requests"
    if recovery.is_dir():
        for path in sorted(recovery.glob("*.json")):
            remove_file(path)

    print("[ OK ] Demo data cleared. User accounts and seed data were kept.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
