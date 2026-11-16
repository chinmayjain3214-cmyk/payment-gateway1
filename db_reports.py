import json

from db import get_connection


def _parse_detail(detail):
    """Return audit detail as a dictionary when possible."""

    if isinstance(detail, dict):
        return detail

    if isinstance(detail, str):
        try:
            parsed = json.loads(detail)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}

    return {}


def latest_log_id():
    """
    Return the ID of the newest agent_log row.

    Returns None if the database cannot be reached.
    """

    try:
        conn = get_connection()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(id), 0) FROM agent_log;"
                )

                row = cur.fetchone()
                return row[0] if row else 0

        finally:
            conn.close()

    except Exception:
        return None


def log_since(last_id):
    """
    Return agent steps logged after last_id, oldest first.

    Returns an empty list if the database is unavailable.
    """

    if last_id is None:
        return []

    try:
        conn = get_connection()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, logged_at, step, detail
                    FROM agent_log
                    WHERE id > %s
                    ORDER BY id ASC;
                    """,
                    (last_id,),
                )

                rows = cur.fetchall()

        finally:
            conn.close()

        return [
            {
                "id": row[0],
                "time": row[1],
                "step": row[2],
                "detail": _parse_detail(row[3]),
            }
            for row in rows
        ]

    except Exception:
        return []


def recent_log(limit=100):
    """
    Return the newest audit-log rows, newest first.

    Raises an exception if the database cannot be reached.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, logged_at, step, detail
                FROM agent_log
                ORDER BY id DESC
                LIMIT %s;
                """,
                (limit,),
            )

            rows = cur.fetchall()

    finally:
        conn.close()

    return [
        {
            "id": row[0],
            "time": row[1],
            "step": row[2],
            "detail": _parse_detail(row[3]),
        }
        for row in rows
    ]