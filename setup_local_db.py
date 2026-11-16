"""One-time local PostgreSQL setup for the invoice agent (Windows).

What it does, in order:
1. Makes sure .env has the DB_* settings. If .env has no DB_PASSWORD, a random
   local password is generated and saved there (.env is git-ignored).
2. Installs PostgreSQL 17 if it is not installed yet. The official installer
   URL and SHA256 come from winget; the file is downloaded with curl (which
   resumes after dropped connections) and verified before it runs. Windows
   will ask for administrator permission once.
3. Waits for the server, then runs db_setup.py, setup_agent_tables.py,
   seed_users.py and (first time only) seed_db.py.
4. Runs check_setup.py so you can see what is still missing.

Safe to run again: existing settings, tables and data are kept (seed_db.py,
which resets demo tables, only runs the first time).
"""

from __future__ import annotations

import glob
import hashlib
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env"
SEED_MARKER = HERE / "data" / ".db_seeded"
WINGET_ID = "PostgreSQL.PostgreSQL.17"

DEFAULTS = {
    "DB_NAME": "invoice_db",
    "DB_USER": "postgres",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
}


LOG_FILE = HERE / "setup.log"  # *.log is git-ignored


def _log(text: str) -> None:
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass


def say(text=""):
    print(text, flush=True)
    _log(str(text))


def run_logged(command, cwd=None, shown_command=None) -> int:
    """Run a command, echo its output to the screen and to setup.log."""
    _log("$ " + (shown_command or " ".join(str(part) for part in command)))
    process = subprocess.Popen(
        command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"),
    )
    for line in process.stdout:
        line = line.rstrip("\r\n")
        # winget redraws its progress bar with \r; keep only the final state.
        shown = line.split("\r")[-1]
        print(shown, flush=True)
        if shown.strip():
            _log(shown)
    return process.wait()


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def ensure_env() -> tuple[dict[str, str], bool]:
    """Add missing DB settings to .env without touching existing lines."""
    values = read_env()
    had_password = bool(values.get("DB_PASSWORD"))
    additions = []

    if not ENV_FILE.exists():
        additions.append("# Local settings for the invoice agent. Never commit this file.")
        additions.append("# Paste your Gemini API key after the = sign:")
        additions.append("GEMINI_API_KEY=")
        values["GEMINI_API_KEY"] = ""

    for key, value in DEFAULTS.items():
        if not values.get(key):
            additions.append(key + "=" + value)
            values[key] = value
    if not had_password:
        password = secrets.token_hex(12)
        additions.append("DB_PASSWORD=" + password)
        values["DB_PASSWORD"] = password

    if additions:
        existing = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        ENV_FILE.write_text(existing + "\n".join(additions) + "\n", encoding="utf-8")
        say("[ OK ] .env updated with database settings (" + str(ENV_FILE.name) + ")")
    else:
        say("[ OK ] .env already has the database settings")
    return values, had_password


def find_pg_bin() -> str | None:
    root = os.environ.get("ProgramFiles", r"C:\Program Files")
    for folder in sorted(glob.glob(os.path.join(root, "PostgreSQL", "*", "bin")), reverse=True):
        if os.path.isfile(os.path.join(folder, "psql.exe")):
            return folder
    return None


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def installer_info() -> tuple[str, str] | None:
    """Official installer URL and SHA256 from the winget package manifest."""
    winget = shutil.which("winget")
    if not winget:
        return None
    result = subprocess.run(
        [winget, "show", "--id", WINGET_ID, "--exact", "--source", "winget",
         "--accept-source-agreements"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    text = result.stdout or ""
    url = re.search(r"Installer Url:\s*(\S+)", text)
    sha = re.search(r"Installer SHA256:\s*([0-9a-fA-F]{64})", text)
    if not url or not sha:
        _log("winget show output:\n" + text + (result.stderr or ""))
        return None
    return url.group(1), sha.group(1).lower()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_installer(url: str, expected_sha: str) -> Path | None:
    """Download with curl, resuming after dropped or expired connections."""
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if not curl:
        say("[FAIL] curl.exe was not found on this PC.")
        return None
    target = Path(os.environ.get("TEMP", str(HERE))) / url.rsplit("/", 1)[-1]

    for attempt in range(1, 31):
        if target.exists() and target.stat().st_size > 0 and sha256_of(target) == expected_sha:
            say("[ OK ] Installer downloaded and verified (SHA256 matches winget)")
            return target
        if attempt > 1:
            say("Download interrupted - resuming (attempt " + str(attempt) + ") ...")
        code = subprocess.run(
            [curl, "-L", "--fail", "-C", "-", "--connect-timeout", "30",
             "-o", str(target), url]
        ).returncode
        _log("curl attempt " + str(attempt) + " exit code " + str(code))
        if code == 33:  # server refused to resume: start over
            target.unlink(missing_ok=True)
        time.sleep(2)

    if target.exists() and sha256_of(target) == expected_sha:
        return target
    say("[FAIL] Could not download a verified installer after several attempts.")
    if target.exists():
        target.unlink(missing_ok=True)
        say("       The partial file failed the SHA256 check and was deleted.")
    return None


def install_postgres(password: str, port: str) -> bool:
    say("Looking up the official PostgreSQL 17 installer in winget ...")
    info = installer_info()
    if info is None:
        say("[FAIL] Could not read the PostgreSQL 17 installer details from winget.")
        say("       Install PostgreSQL 17 from https://www.postgresql.org/download/windows/")
        say("       and use the DB_PASSWORD value from .env as the postgres password.")
        return False
    url, expected_sha = info
    say("Downloading " + url)
    say("(about 400 MB; it resumes automatically if the connection drops)")
    installer = download_installer(url, expected_sha)
    if installer is None:
        return False

    say()
    say(">>> Windows will now ask for administrator permission. Click YES. <<<")
    say("Installing PostgreSQL 17 - this takes a few minutes, please wait ...")
    args = (
        "--mode unattended --unattendedmodeui minimal"
        " --superpassword " + password +
        " --serverport " + port +
        " --enable-components server,commandlinetools"
    )
    ps_command = (
        "$p = Start-Process -FilePath '" + str(installer).replace("'", "''") + "'"
        " -ArgumentList '" + args.replace("'", "''") + "'"
        " -Verb RunAs -Wait -PassThru; exit $p.ExitCode"
    )
    _log("$ Start-Process " + installer.name + " (elevated, password hidden)")
    result = subprocess.run(["powershell", "-NoProfile", "-Command", ps_command])
    _log("installer exit code " + str(result.returncode))

    if find_pg_bin():
        say("[ OK ] PostgreSQL is installed")
        return True
    say("[FAIL] PostgreSQL installation did not finish (exit code "
        + str(result.returncode) + ").")
    say("       If you clicked No on the administrator prompt, run this again and click Yes.")
    return False


def wait_for_server(host: str, port: int, seconds: int = 90) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_open(host, port):
            return True
        time.sleep(3)
    return False


def check_login(values: dict[str, str]) -> bool:
    import psycopg2

    try:
        conn = psycopg2.connect(
            dbname="postgres",
            user=values["DB_USER"],
            password=values["DB_PASSWORD"],
            host=values["DB_HOST"],
            port=values["DB_PORT"],
        )
        conn.close()
        return True
    except Exception as exc:
        say("[FAIL] Could not log in to PostgreSQL: " + str(exc).strip()[:200])
        return False


def run_step(script: str) -> bool:
    say()
    say("----- python " + script + " -----")
    code = run_logged([sys.executable, script], cwd=HERE)
    if code != 0:
        say("[FAIL] " + script + " exited with code " + str(code))
        return False
    return True


def main() -> int:
    _log("\n===== " + time.strftime("%Y-%m-%d %H:%M:%S") + " =====")
    say("Invoice agent - local database setup")
    say("=====================================")
    os.chdir(HERE)

    pg_bin = find_pg_bin()
    values, had_password = ensure_env()

    if pg_bin is None:
        if not install_postgres(values["DB_PASSWORD"], values["DB_PORT"]):
            return 1
    else:
        say("[ OK ] PostgreSQL found at " + pg_bin)
        if not had_password:
            say("[FAIL] PostgreSQL was already installed, so its postgres password is not")
            say("       the one just written to .env. Open .env and set DB_PASSWORD to the")
            say("       password you chose when you installed PostgreSQL, then run this again.")
            return 1

    host, port = values["DB_HOST"], int(values["DB_PORT"])
    say("Waiting for the PostgreSQL server on " + host + ":" + str(port) + " ...")
    if not wait_for_server(host, port):
        say("[FAIL] The server is not answering. Open Services (services.msc), find")
        say("       'postgresql-x64-17' and click Start, then run this again.")
        return 1
    say("[ OK ] PostgreSQL server is running")

    if not check_login(values):
        say("       Check DB_USER and DB_PASSWORD in .env.")
        return 1
    say("[ OK ] Logged in to PostgreSQL")

    for script in ("db_setup.py", "setup_agent_tables.py", "seed_users.py"):
        if not run_step(script):
            return 1

    if not SEED_MARKER.exists():
        if run_step("seed_db.py"):
            SEED_MARKER.parent.mkdir(parents=True, exist_ok=True)
            SEED_MARKER.write_text("seeded\n", encoding="utf-8")

    run_step("check_setup.py")
    say()
    say("Database setup finished. Close any old app window and start run_app.bat.")
    if not values.get("GEMINI_API_KEY"):
        say("Note: add your GEMINI_API_KEY to .env so the AI invoice reading works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
