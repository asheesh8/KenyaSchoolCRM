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
DATA = Path(os.environ.get("HARVEST_DATA", ROOT / "data"))
CACHE = DATA / "cache"
DB_PATH = Path(os.environ.get("HARVEST_DB", DATA / "harvest.db"))
UI_DIR = ROOT / "ui"

# Identifies the crawler to school webmasters. Set HARVEST_CONTACT to a URL or
# email address where a school can reach you.
CONTACT = os.environ.get("HARVEST_CONTACT", "")
USER_AGENT = "KenyaSchoolsDirectory/1.0 (school outreach directory{})".format(
    "; +" + CONTACT if CONTACT else ""
)
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 " + USER_AGENT
)

GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")

# Hosted deployment (Vercel): data lives in Turso, and a password guards the CRM.
TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "") or APP_PASSWORD
ON_VERCEL = bool(os.environ.get("VERCEL"))

OVERPASS_ENDPOINTS = [
    u.strip()
    for u in os.environ.get(
        "HARVEST_OVERPASS",
        "https://overpass.private.coffee/api/interpreter,https://overpass-api.de/api/interpreter,"
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ).split(",")
    if u.strip()
]
# Kenya's bounding box; results are clipped to the national boundary afterwards.
KENYA_BBOX = (-4.72, 33.90, 5.03, 41.91)  # south, west, north, east

# Ministry of Education school list (2010 edition, ~72k teaching units), as
# published on the Humanitarian Data Exchange: data.humdata.org/dataset/kenya-schools
MOE_SHEET_URL = ("https://docs.google.com/spreadsheets/d/1t8S_POnyZnSJWMtgutAdKYnhQXu4L6nS_XKPcryImso"
                 "/export?format=csv")
# World Bank / Ministry of Education 2017 edition (energydata.info/dataset/kenya-schools).
# That host sits behind a browser check, so it isn't downloaded automatically:
# save it by hand to data/cache/wb_schools.json (GeoJSON) and `moe` picks it up.
WB_SCHOOLS_FILE = "wb_schools.json"
WB_SCHOOLS_URL = ("https://energydata.info/dataset/2fda191d-c3c6-4002-8c82-daa02008a9e3/resource/"
                  "129b8c79-de8b-4b7b-8310-cdd207e46863/download/schools.json")

# OCHA administrative boundaries (47 counties, 290 sub-counties) and 2019 census populations.
ADMIN_BOUNDARIES_URL = ("https://data.humdata.org/dataset/2c0b7571-4bef-4347-9b81-b2174c13f9ef/resource/"
                        "674ea496-5451-4312-bcab-8aa95fa3f36c/download/ken_admin_boundaries.geojson.zip")
ADMIN_POP_URL = ("https://data.humdata.org/dataset/26801642-7088-4149-9605-6ae282897937/resource/"
                 "e57fb9a8-96dc-4a21-849b-1ddbc4ed7803/download/ken_admpop_2019.xlsx")
HOT_OSM_URL = ("https://production-raw-data-api.s3.amazonaws.com/ISO3/KEN/education_facilities/"
               "hotosm_ken_education_facilities_osm_geojson.zip")
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"


def ensure_dirs():
    if ON_VERCEL:
        return  # read-only filesystem; nothing is written locally there
    DATA.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
