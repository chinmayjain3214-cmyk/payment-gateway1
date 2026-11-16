import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

HERE = Path(__file__).parent
REQUIRED_TABLES = [
    "vendors", "purchase_orders", "goods_receipts", "invoices", "audit_logs",
    "agent_log", "approval_requests", "users",
]

problems = 0
warnings = 0


def ok(text):
    print("[ OK ] " + text)


def warn(text):
    global warnings
    warnings += 1
    print("[WARN] " + text)


def fail(text):
    global problems
    problems += 1
    print("[FAIL] " + text)


def check_settings():
    print("\nSettings")
    if os.getenv("GEMINI_API_KEY"):
        ok("GEMINI_API_KEY is set")
    else:
        fail("GEMINI_API_KEY is missing in .env")
    if os.getenv("DB_PASSWORD"):
        ok("DB_PASSWORD is set")
    else:
        warn("DB_PASSWORD is empty. That is only fine if your PostgreSQL has no password.")
    ok("Main model: " + os.getenv("MODEL", "gemini-3.1-flash-lite (default)"))
    if os.getenv("FALLBACK_MODEL"):
        ok("Fallback model: " + os.getenv("FALLBACK_MODEL"))
    else:
        warn("No FALLBACK_MODEL in .env, so a busy main model has no backup.")

    gitignore = HERE / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    if ".env" in [line.strip() for line in lines]:
        ok(".env is listed in .gitignore, so your keys stay private")
    else:
        fail(".env is NOT listed in .gitignore. Add a line with .env before you push.")


def check_files():
    print("\nFiles")
    invoice_dir = HERE / "invoices"
    invoices = [p for p in invoice_dir.glob("*") if p.is_file() and not p.name.startswith("upload_")] if invoice_dir.exists() else []
    if invoices:
        ok(str(len(invoices)) + " demo invoices in the invoices folder")
    else:
        warn("No demo invoices found in the invoices folder")
    cache_dir = HERE / "extracted"
    cached = list(cache_dir.glob("*.json")) if cache_dir.exists() else []
    if cached:
        ok(str(len(cached)) + " invoice readings saved in the extracted folder (demo works even if Gemini is slow)")
    else:
        warn("No saved invoice readings yet. Run python run_invoices.py once to create them.")


def check_database():
    print("\nDatabase")
    try:
        from db import get_connection
        conn = get_connection()
    except Exception as e:
        fail("Cannot connect to PostgreSQL: " + str(e)[:120])
        return
    try:
        with conn.cursor() as cur:
            ok("Connected to PostgreSQL")
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
            existing = {row[0] for row in cur.fetchall()}
            for table in REQUIRED_TABLES:
                if table in existing:
                    ok("Table " + table + " exists")
                else:
                    fail("Table " + table + " is missing. Run python db_setup.py and python setup_agent_tables.py")
            if "users" in existing:
                cur.execute("SELECT role, COUNT(*) FROM users GROUP BY role;")
                counts = dict(cur.fetchall())
                for role in ("vendor", "approver", "admin"):
                    if counts.get(role):
                        ok("The " + role + " demo account exists")
                    else:
                        fail("No " + role + " account. Run python seed_users.py")
    finally:
        conn.close()


def check_gemini():
    print("\nGemini")
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        warn("Skipped, because there is no key")
        return
    try:
        from google import genai
        client = genai.Client(api_key=key, http_options={"timeout": 20000})
    except Exception as e:
        fail("The Gemini library could not start: " + str(e)[:120])
        return

    models = [os.getenv("MODEL", "gemini-3.1-flash-lite")]
    if os.getenv("FALLBACK_MODEL"):
        models.append(os.getenv("FALLBACK_MODEL"))
    answered = 0
    for model in models:
        try:
            client.models.generate_content(model=model, contents="Reply with the single word OK.")
            ok("Model " + model + " answered")
            answered += 1
        except Exception as e:
            warn("Model " + model + " did not answer: " + str(e)[:80])
    if answered == 0:
        fail("No Gemini model answered. Check your internet connection and the model names in .env")


def check_streamlit():
    print("\nApp")
    try:
        import streamlit
        ok("Streamlit " + streamlit.__version__ + " is installed")
    except ImportError:
        fail("Streamlit is not installed. Run: pip install streamlit")


def main():
    print("Preflight check before the demo")
    check_settings()
    check_files()
    check_database()
    check_gemini()
    check_streamlit()

    print()
    if problems:
        print(str(problems) + " problem(s) to fix before the demo.")
        sys.exit(1)
    if warnings:
        print("Ready, with " + str(warnings) + " warning(s) to look at.")
    else:
        print("Everything looks ready for the demo.")


if __name__ == "__main__":
    main()
    