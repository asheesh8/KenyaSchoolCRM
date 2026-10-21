"""Kenya: the harvester's database (data/harvest.db, or the live Turso copy) -> the shared format.

The Kenya directory is built by `python3 -m harvest` in the repository root, which keeps
its own richer schema. `python3 -m africacrm import-kenya` reads it, writes
dataset/kenya-schools.jsonl in the shared format, loads it, and carries over the CRM work
already done in the Kenya CRM: stages, stars, tags and the activity log.
"""

import json
import sqlite3

from . import db, importer, levels
from .countries import get

KE = get("KE")
# The harvester's level bits (harvest/levels.py) -> shared keys.
_LEVEL_BITS = {1: "pre_primary", 2: "primary", 4: "lower_secondary", 8: "upper_secondary", 16: "tvet",
               32: "tertiary", 64: "tertiary", 256: "primary"}
_CONFIDENCE = {"manual": "high", "web": "high", "places": "medium", "osm": "medium", "wikidata": "medium",
               "list": "medium"}
_STATUS = {"visit": "interested"}


def open_source(path=None, url=None, token=None):
    if url:
        from . import remote
        return remote.connect(url, token or "")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _pages(conn, sql, size=2000):
    off = 0
    while True:
        rows = conn.execute(f"{sql} LIMIT {size} OFFSET {off}").fetchall()
        if not rows:
            return
        yield from rows
        off += size


def _get(r, k):
    try:
        return r[k]
    except (IndexError, KeyError):
        return None


def to_record(s, contacts):
    keys_ = []
    for bit, key in _LEVEL_BITS.items():
        if (s["levels"] or 0) & bit and key not in keys_:
            keys_.append(key)
    emails, phones, officials, website = [], [], [], s["website"]
    for c in contacts:
        conf = _CONFIDENCE.get(c["source"], "low")
        url = c["source_url"] or (f"https://www.openstreetmap.org/{s['osm_id']}" if c["source"] == "osm" and
                                  _get(s, "osm_id") else None)
        if c["kind"] == "email":
            emails.append({"email": c["value"].lower(), "source_url": url, "confidence": conf, "seen": None,
                           "person": None, "role": c["label"], "active": c["active"]})
        elif c["kind"] == "phone" and c["label"] != "fax":
            num = KE.clean_phone(c["value"])
            if num and num not in {p["phone"] for p in phones}:
                phones.append({"phone": num, "source_url": url, "active": c["active"]})
        elif c["kind"] == "person" and c["active"]:
            officials.append({"name": c["value"], "role": c["label"], "email": None, "phone": None, "source_url": url})
        elif c["kind"] == "website" and not website:
            website = c["value"]
    ownership = {"private": "private", "public": "government"}.get(s["ownership"] or "", "unknown")
    if ownership == "unknown" and s["sponsor"] in ("religious",):
        ownership = "mission"
    sources = json.loads(s["sources"] or "[]")
    return {
        "id": f"ke-{s['id']}", "country": "KE", "name": s["name"], "kind": "school",
        "levels": sorted(keys_, key=levels.BIT.get),
        "province": s["province"] or KE.province(KE.canonical_district(s["county"])),
        "district": KE.canonical_district(s["county"]) or s["county"], "area": s["subcounty"],
        "town": s["town"], "address": _get(s, "address") or s["postal_address"], "ownership": ownership,
        "denomination": s["faith"], "website": website, "emails": emails, "phones": phones, "officials": officials,
        "emis_code": s["nemis_code"], "lat": s["lat"], "lon": s["lon"], "students": s["students"],
        "setting": s["setting"], "gender": s["gender"], "boarding": s["boarding"],
        "sources": [u for u in sources if isinstance(u, str)], "notes": None,
    }


def export(src):
    """Every Kenyan school as shared-format records, plus each one's CRM state."""
    contacts = {}
    for c in _pages(src, "SELECT school_id, kind, value, label, source, source_url, active FROM contacts "
                         "WHERE kind IN ('email','phone','person','website') ORDER BY id"):
        contacts.setdefault(c["school_id"], []).append(c)
    records, crm = [], {}
    for s in _pages(src, "SELECT * FROM schools ORDER BY id"):
        rec = to_record(s, contacts.get(s["id"], []))
        records.append(rec)
        if s["status"] != "new" or s["starred"] or s["tags"] not in (None, "", "[]"):
            crm[rec["id"]] = {"status": _STATUS.get(s["status"], s["status"]), "starred": s["starred"],
                              "tags": s["tags"] or "[]", "touched_at": s["touched_at"], "old_id": s["id"]}
    return records, crm


def regions(src):
    try:
        rows = src.execute("SELECT name, population, school_age FROM areas WHERE kind='county'").fetchall()
    except Exception:
        return []
    return [(KE.canonical_district(r["name"]) or r["name"], r["population"], r["school_age"]) for r in rows]


def import_kenya(conn, path=None, url=None, token=None, out=None):
    src = open_source(path, url, token)
    records, crm = export(src)
    if out:
        importer.write_jsonl([{k: v for k, v in r.items()} for r in records], out)
    stats, ids = importer.load_records(conn, records, "KE", source="harvest")
    moved = 0
    for ref, st in crm.items():
        sid = ids.get(ref)
        if not sid:
            continue
        cur = conn.execute("SELECT status FROM schools WHERE id=?", (sid,)).fetchone()
        if cur["status"] == "new" and st["status"] in db.STATUSES:
            conn.execute("UPDATE schools SET status=? WHERE id=?", (st["status"], sid))
        conn.execute("UPDATE schools SET starred=MAX(starred, ?), tags=?, touched_at=COALESCE(touched_at, ?) "
                     "WHERE id=?", (st["starred"] or 0, st["tags"], st["touched_at"], sid))
        moved += 1
    acts = 0
    for a in _pages(src, "SELECT school_id, kind, body, created_at FROM activities ORDER BY id"):
        sid = ids.get(f"ke-{a['school_id']}")
        if sid and not conn.execute("SELECT 1 FROM activities WHERE school_id=? AND created_at=? AND body IS ?",
                                    (sid, a["created_at"], a["body"])).fetchone():
            conn.execute("INSERT INTO activities(school_id, kind, body, created_at) VALUES (?,?,?,?)",
                         (sid, a["kind"], a["body"], a["created_at"]))
            acts += 1
    for district, pop, age in regions(src):
        conn.execute("INSERT INTO regions(country, district, province, population, school_age) VALUES ('KE',?,?,?,?) "
                     "ON CONFLICT(country, district) DO UPDATE SET population=excluded.population, "
                     "school_age=excluded.school_age", (district, KE.province(district), pop, age))
    conn.commit()
    return {**stats, "crm_state_carried_over": moved, "activities_copied": acts, "file": str(out) if out else None}
