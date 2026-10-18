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
DATA = Path(os.environ.get("SLCRM_DATA", ROOT / "data"))
CACHE = DATA / "cache"
DB_PATH = Path(os.environ.get("SLCRM_DB", DATA / "crm.db"))
UI_DIR = ROOT / "ui"
DATASET_DIR = ROOT / "dataset"
# The merged contacts are kept out of the public repository; `load` reads this file.
DATASET = Path(os.environ.get("SLCRM_DATASET", DATASET_DIR / "sierra-leone-schools.jsonl"))
# Where the research workers drop their raw files (one JSONL per worker).
RAW_DIR = Path(os.environ.get("SLCRM_RAW", "/mnt/project-files/sierra-leone-schools/raw"))

CONTACT = os.environ.get("HARVEST_CONTACT", "")
USER_AGENT = "SierraLeoneSchoolsDirectory/1.0 (school outreach directory{})".format(
    "; +" + CONTACT if CONTACT else "")

# Hosted deployment (Vercel): data lives in Turso, and a password guards the CRM.
TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
# Signs session cookies and unsubscribe links, and encrypts SMTP passwords saved in the database.
SECRET_KEY = os.environ.get("SECRET_KEY", "") or APP_PASSWORD or "change-me-local-only"
ON_VERCEL = bool(os.environ.get("VERCEL"))
# Public address of this CRM (e.g. https://sl-schools.vercel.app). Needed for one-click unsubscribe links.
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")

OVERPASS_ENDPOINTS = [
    u.strip()
    for u in os.environ.get(
        "HARVEST_OVERPASS",
        "https://overpass-api.de/api/interpreter,https://overpass.private.coffee/api/interpreter,"
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ).split(",")
    if u.strip()
]
SL_BBOX = (6.85, -13.40, 10.00, -10.25)  # south, west, north, east
# HOT OSM export of Sierra Leone education facilities (refreshed regularly by HOT).
HOT_OSM_URL = ("https://production-raw-data-api.s3.amazonaws.com/ISO3/SLE/education_facilities/"
               "hotosm_sle_education_facilities_osm_geojson.zip")

MAX_ACCOUNTS = 7


def ensure_dirs():
    if ON_VERCEL:
        return
    DATA.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
