
"""Initialize all PostgreSQL schemas for the invoice agent."""

from pathlib import Path

from db import get_connection
from approval_workflow import _ensure_schema

BASE_DIR = Path(__file__).resolve().parent

SCHEMA_FILES = [
    BASE_DIR / "schema.sql",
    BASE_DIR / "schema_agent.sql",
]


def main():
    for schema_file in SCHEMA_FILES:
        if not schema_file.is_file():
            raise FileNotFoundError(
                "Required schema file is missing: " + str(schema_file)
            )

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            # Create core and agent tables.
            for schema_file in SCHEMA_FILES:
                sql = schema_file.read_text(encoding="utf-8")
                cur.execute(sql)
                print("Applied:", schema_file.name)

            # Create the three-stage approval workflow table.
            _ensure_schema(cur)
            print("Applied: approval workflow schema")

            # Verify all required tables.
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """)

            tables = [row[0] for row in cur.fetchall()]

        conn.commit()

        print("\nDatabase setup completed successfully.")
        print("\nAvailable tables:")

        for table in tables:
            print(" -", table)

        required = {
            "vendors",
            "purchase_orders",
            "goods_receipts",
            "invoices",
            "audit_logs",
            "agent_log",
            "approval_requests",
            "approval_workflow_stages",
            "payment_schedules",
            "users",
        }

        missing = required - set(tables)

        if missing:
            raise RuntimeError(
                "Missing required database tables: "
                + ", ".join(sorted(missing))
            )

        print("\nAll required database tables are present.")

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()
