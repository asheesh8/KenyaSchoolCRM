"""OpenStreetMap schools, colleges and universities in Uganda, from HOT's country export.

The export already carries each facility's region, district, county and sub-county, so
every mapped school lands in the right place. It has names, coordinates and operator type
but no contacts: it is the base list the researched contacts are matched onto.
Writes raw/osm.jsonl in the research schema.
"""

import io
import json
import os
import urllib.request
import zipfile

from . import config, levels

AMENITY_LEVELS = {"kindergarten": ["pre_primary"], "university": ["tertiary"], "college": ["tertiary"]}
OWNERSHIP = {"public": "government", "government": "government", "local_authority": "government",
             "private": "private", "religious": "mission", "church": "mission", "community": "community",
             "ngo": "ngo", "n.g.o": "ngo"}


def download(path=None):
    path = path or config.CACHE / "hotosm_uga_education_facilities.zip"
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        req = urllib.request.Request(config.HOT_OSM_URL, headers={"User-Agent": config.USER_AGENT})
        with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as f:
            f.write(r.read())
    return path


def _features(path):
    with open(path, "rb") as f:
        head = f.read(2)
    if head == b"PK":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.endswith(".geojson"))
            data = json.load(io.TextIOWrapper(z.open(name), encoding="utf-8"))
    else:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    return data.get("features", [])


def _centre(geom):
    if not geom:
        return None, None
    if geom["type"] == "Point":
        lon, lat = geom["coordinates"][:2]
        return round(lat, 6), round(lon, 6)
    pts = []

    def walk(c):
        if c and isinstance(c[0], (int, float)):
            pts.append(c)
        else:
            for x in c:
                walk(x)
    walk(geom.get("coordinates") or [])
    if not pts:
        return None, None
    return round(sum(p[1] for p in pts) / len(pts), 6), round(sum(p[0] for p in pts) / len(pts), 6)


def to_record(feat):
    p = feat.get("properties") or {}
    name = " ".join((p.get("name") or p.get("name_en") or "").split())
    if not name or len(name) < 3:
        return None
    amenity = p.get("amenity")
    if amenity not in (None, "school", "kindergarten", "college", "university"):
        return None
    lv = levels.levels_from_name(name)
    guessed = False
    if not lv:
        lv = list(AMENITY_LEVELS.get(amenity, []))
    if not lv:
        # Most of Uganda's schools are primary schools, and a bare "X School" on the map usually is one.
        lv, guessed = ["primary"], True
    lat, lon = _centre(feat.get("geometry"))
    district = levels.canonical_district(p.get("adm2_name"))
    osm_url = "https://www.openstreetmap.org/" + str(p.get("id") or "")
    op = (p.get("operator_type") or "").strip().lower()
    return {
        "name": name, "kind": "school", "levels": lv, "region": p.get("adm1_name") or levels.region(district),
        "district": district, "county": p.get("adm3_name"), "area": p.get("adm4_name"),
        "town": p.get("addr_city") or None, "address": p.get("addr_full") or None,
        "ownership": OWNERSHIP.get(op) or ("mission" if op and ("church" in op or "catholic" in op) else None),
        "denomination": levels.faith_from_name(name), "website": None, "emails": [], "phones": [], "officials": [],
        "emis_code": None, "lat": lat, "lon": lon, "students": None, "sources": [osm_url],
        "notes": "Mapped on OpenStreetMap" + ("; level guessed (name gives none)" if guessed else ""),
        "osm_id": p.get("id"), "worker": "osm",
    }


def harvest(path=None, raw_dir=None):
    path = path or download()
    raw_dir = raw_dir or config.RAW_DIR
    out, seen = [], set()
    for feat in _features(path):
        rec = to_record(feat)
        if rec and rec["osm_id"] not in seen:
            seen.add(rec["osm_id"])
            out.append(rec)
    os.makedirs(raw_dir, exist_ok=True)
    with open(os.path.join(raw_dir, "osm.jsonl"), "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"facilities": len(out), "file": os.path.join(str(raw_dir), "osm.jsonl")}
