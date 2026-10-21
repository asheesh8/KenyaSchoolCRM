import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """KEY=value lines from a local, untracked .env; real environment variables win."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file(ROOT / ".env")
DATA = Path(os.environ.get("AFRICACRM_DATA", ROOT / "data"))
DB_PATH = Path(os.environ.get("AFRICACRM_DB", DATA / "crm.db"))
UI_DIR = ROOT / "ui"
DATASET_DIR = ROOT / "dataset"
# The shared project folder, where each country's research lives (kept out of the public repository).
PROJECT_FILES = Path(os.environ.get("AFRICACRM_PROJECT_FILES", "/mnt/project-files"))

# Hosted deployment (Vercel): data lives in Turso, and a password guards the CRM.
TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
# Signs session cookies and unsubscribe links, and encrypts SMTP passwords saved in the database.
SECRET_KEY = os.environ.get("SECRET_KEY", "") or APP_PASSWORD or "change-me-local-only"
ON_VERCEL = bool(os.environ.get("VERCEL"))
# Public address of this CRM (e.g. https://africa-schools.vercel.app). Needed for one-click unsubscribe links.
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
# Lets a scheduler (Vercel Cron, cron-job.org, GitHub Actions) drive sending with no browser open.
CRON_SECRET = os.environ.get("CRON_SECRET", "")

MAX_ACCOUNTS = int(os.environ.get("MAX_ACCOUNTS", 7))


def ensure_dirs():
    if ON_VERCEL:
        return
    DATA.mkdir(parents=True, exist_ok=True)
