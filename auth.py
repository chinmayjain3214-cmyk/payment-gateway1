
import hashlib
import hmac
import secrets

from db import get_connection
from db_store import save_log


ITERATIONS = 200_000

ALLOWED_ROLES = {
    "vendor",
    "procurement_officer",
    "department_head",
    "finance_officer",
    "final_approver",
    "approver",  # Backward-compatible alias for the final approval stage.
    "admin",
}


def hash_password(password):
    """Generate a salted PBKDF2 password hash."""

    if not isinstance(password, str) or not password:
        raise ValueError("Password cannot be empty.")

    salt = secrets.token_hex(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        ITERATIONS,
    )

    return (
        "pbkdf2_sha256$"
        + str(ITERATIONS)
        + "$"
        + salt
        + "$"
        + digest.hex()
    )


def verify_password(password, stored):
    """Verify a password against its stored hash."""

    try:
        if not isinstance(password, str):
            return False

        if not isinstance(stored, str):
            return False

        algorithm, iterations, salt, expected = stored.split("$")

        if algorithm != "pbkdf2_sha256":
            return False

        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            int(iterations),
        )

        return hmac.compare_digest(
            digest.hex(),
            expected,
        )

    except (ValueError, TypeError, AttributeError):
        return False


def create_user(username, full_name, role, password):
    """Create a user or update an existing demo account."""

    username = str(username).strip().lower()
    full_name = str(full_name).strip()
    role = str(role).strip().lower()

    if not username:
        raise ValueError("Username cannot be empty.")

    if not full_name:
        raise ValueError("Full name cannot be empty.")

    if role not in ALLOWED_ROLES:
        raise ValueError("Invalid user role: " + role)

    password_hash = hash_password(password)

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users
                    (username, full_name, role, password_hash)
                VALUES (%s, %s, %s, %s)

                ON CONFLICT (username)
DO UPDATE SET
    full_name = EXCLUDED.full_name,
    role = EXCLUDED.role,
    password_hash = EXCLUDED.password_hash;
                """,
                (
                    username,
                    full_name,
                    role,
                    password_hash,
                ),
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def authenticate(username, password):
    """Authenticate a user and return account information."""

    username = str(username or "").strip().lower()

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT username, full_name, role, password_hash
                FROM users
                WHERE username = %s;
                """,
                (username,),
            )

            row = cur.fetchone()

    finally:
        conn.close()

    if (
        row
        and row[2] in ALLOWED_ROLES
        and verify_password(password, row[3])
    ):
        save_log(
            "auth:login",
            {
                "user": row[0],
                "role": row[2],
            },
        )

        return {
            "username": row[0],
            "full_name": row[1],
            "role": row[2],
        }

    save_log(
        "auth:login_failed",
        {"user": username[:50]},
    )

    return None
