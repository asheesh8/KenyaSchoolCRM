"""OpenStreetMap schools, colleges and universities in Sierra Leone (Overpass API).

Adds every mapped school with its coordinates, and any phone, email, website or
operator the map records. Matches existing records by name within the same district,
or by distance (under 300 m with a similar name). Run on your own computer: it needs
open internet access.
"""

import json
import math
import urllib.parse

from . import config, db, levels
from .net import log, request

QUERY = """[out:json][timeout:180];
area["ISO3166-1"="SL"][admin_level=2]->.sl;
(nwr["amenity"~"^(school|kindergarten|college|university)$"](area.sl);
 nwr["building"="school"]["name"](area.sl););
out center tags;"""

AMENITY_LEVELS = {"kindergarten": ["pre_primary"], "college": ["tvet"], "university": ["tertiary"]}
ISCED = {"0": "pre_primary", "1": "primary", "2": "junior_secondary", "3": "senior_secondary", "4": "tvet",
         "5": "tertiary", "6": "tertiary"}


def fetch():
    last = None
    for ep in config.OVERPASS_ENDPOINTS:
        try:
            log(f"  asking {urllib.parse.urlsplit(ep).netloc}")
            return json.loads(request(ep, data=urllib.parse.urlencode({"data": QUERY}), timeout=240))
        except Exception as e:  # try the next public server
            last = e
            log(f"  {ep}: {e}")
    raise SystemExit(f"Every Overpass server failed: {last}")


def _km(a, b, c, d):
    return 6371 * 2 * math.asin(math.sqrt(math.sin(math.radians(c - a) / 2) ** 2 + math.cos(math.radians(a)) *
                                          math.cos(math.radians(c)) * math.sin(math.radians(d - b) / 2) ** 2))


def ingest(conn):
    data = fetch()
    t = db.now()
    stats = {"seen": 0, "added": 0, "matched": 0, "emails": 0, "phones": 0}
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = (tags.get("name") or tags.get("name:en") or "").strip()
        if not name:
            continue
        stats["seen"] += 1
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        osm_id = f"{el['type'][0]}{el['id']}"
        lv = list(AMENITY_LEVELS.get(tags.get("amenity"), []))
        for part in (tags.get("isced:level") or "").replace(",", ";").split(";"):
            k = ISCED.get(part.strip()[:1])
            if k and k not in lv:
                lv.append(k)
        lv = lv or levels.levels_from_name(name) or ["primary"]
        district = levels.canonical_district(tags.get("addr:district")) or levels.district_from_text(
            tags.get("addr:city"), tags.get("addr:town"), tags.get("is_in"))
        norm = levels.norm_name(name)
        row = conn.execute("SELECT * FROM schools WHERE osm_id=?", (osm_id,)).fetchone()
        if not row and district:
            row = conn.execute("SELECT * FROM schools WHERE norm=? AND district=?", (norm, district)).fetchone()
        if not row and lat:
            for c in conn.execute("SELECT * FROM schools WHERE norm=? AND lat IS NOT NULL", (norm,)).fetchall():
                if _km(lat, lon, c["lat"], c["lon"]) < 0.3:
                    row = c
                    break
        op = (tags.get("operator:type") or "").lower()
        ownership = {"government": "government", "public": "government", "private": "private",
                     "religious": "mission", "community": "community", "ngo": "ngo"}.get(op)
        if row:
            sid = row["id"]
            conn.execute("UPDATE schools SET osm_id=COALESCE(osm_id, ?), lat=COALESCE(lat, ?), lon=COALESCE(lon, ?), "
                         "levels=levels|?, district=COALESCE(district, ?), sources=?, updated_at=? WHERE id=?",
                         (osm_id, lat, lon, levels.mask(lv), district, db.add_sources(row["sources"], "osm"), t, sid))
            stats["matched"] += 1
        else:
            cur = conn.execute(
                "INSERT INTO schools(name, norm, kind, levels, ownership, denomination, district, province, town, "
                "lat, lon, osm_id, sources, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (name, norm, "school", levels.mask(lv), ownership or "unknown",
                 tags.get("denomination") or levels.faith_from_name(name), district,
                 levels.province(district), tags.get("addr:city"), lat, lon, osm_id, json.dumps(["osm"]), t, t))
            sid = cur.lastrowid
            stats["added"] += 1
        src = f"https://www.openstreetmap.org/{el['type']}/{el['id']}"
        for key in ("email", "contact:email"):
            e = levels.clean_email(tags.get(key))
            if e:
                db.upsert_contact(conn, sid, "email", e, "osm", source_url=src, confidence="medium", ts=t)
                stats["emails"] += 1
        for key in ("phone", "contact:phone", "contact:mobile"):
            for p in (tags.get(key) or "").split(";"):
                p = levels.clean_phone(p)
                if p:
                    db.upsert_contact(conn, sid, "phone", p, "osm", source_url=src, ts=t)
                    stats["phones"] += 1
        for key in ("website", "contact:website"):
            if (tags.get(key) or "").startswith("http"):
                db.upsert_contact(conn, sid, "website", tags[key], "osm", source_url=src, ts=t)
        db.refresh_primary(conn, sid)
    conn.commit()
    return stats
