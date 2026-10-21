import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("UG_DATA", ROOT / "data"))
CACHE = DATA / "cache"
# Raw research files (one JSONL per research worker) and the merged output. Both default to the project folder,
# because the contacts are kept out of the public repository.
RAW_DIR = Path(os.environ.get("UG_RAW", "/mnt/project-files/uganda-schools/raw"))
DATASET_DIR = Path(os.environ.get("UG_DATASET_DIR", "/mnt/project-files/uganda-schools"))
DATASET_NAME = "uganda-schools.jsonl"
COUNTRY = "UG"

CONTACT = os.environ.get("HARVEST_CONTACT", "")
USER_AGENT = "UgandaSchoolsDirectory/1.0 (school outreach directory{})".format("; +" + CONTACT if CONTACT else "")

# HOT's OpenStreetMap export of Uganda's education facilities, with admin areas already joined
# (region, district, county, sub-county). Refreshed regularly; no key needed.
HOT_OSM_URL = ("https://production-raw-data-api.s3.amazonaws.com/ISO3/UGA/education_facilities/"
               "hotosm_uga_education_facilities_osm_geojson.zip")
