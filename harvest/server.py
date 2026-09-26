"""The CRM: a JSON API over the SQLite directory, plus the static UI in ui/."""

import csv
import hashlib
import hmac
import io
import json
import mimetypes
import re
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from . import config, db, levels
from .net import log

_local = threading.local()
_refresh_lock = threading.Lock()


def conn():
    c = getattr(_local, "conn", None)
    if c is None:
        c = _local.conn = db.connect()
    return c


SORTS = {
    # Most reachable first: named head, email, phone, then the biggest schools.
    "best": ["(s.leader IS NOT NULL) DESC", "(s.email IS NOT NULL) DESC", "(s.phone IS NOT NULL) DESC",
             "(s.website IS NOT NULL) DESC", "COALESCE(s.students, s.classrooms * 40, 0) DESC", "s.name COLLATE NOCASE"],
    "name": ["s.name COLLATE NOCASE {dir}"],
    "county": ["s.county {dir}", "s.subcounty {dir}", "s.name COLLATE NOCASE"],
    "size": ["COALESCE(s.students, s.classrooms * 40) {dir} NULLS LAST", "s.name COLLATE NOCASE"],
    "population": ["sc.population {dir} NULLS LAST", "s.name COLLATE NOCASE"],
    "density": ["s.pop_density {dir} NULLS LAST"],
    "status": ["s.status {dir}", "s.name COLLATE NOCASE"],
    "verified": ["s.enriched_at {dir} NULLS LAST"],
    "touched": ["s.touched_at {dir} NULLS LAST"],
}
DEFAULT_DIR = {"size": "DESC", "population": "DESC", "density": "DESC", "verified": "DESC", "touched": "DESC"}
LIST_COLS = """s.id, s.name, s.levels, s.grade_min, s.grade_max, s.ownership, s.sponsor, s.faith, s.gender,
    s.boarding, s.special_needs, s.county, s.subcounty, s.county_code, s.subcounty_code, s.town, s.location,
    s.lat, s.lon, s.setting, s.pop_density, s.classrooms, s.students, s.teachers, s.email, s.phone, s.website,
    s.leader, s.postal_address, s.address, s.status, s.starred, s.tags, s.enrich_status, s.enriched_at, s.touched_at,
    s.sources, sc.population AS const_pop, co.population AS county_pop"""
FROM = ("FROM schools s LEFT JOIN areas sc ON sc.code=s.subcounty_code "
        "LEFT JOIN areas co ON co.code=s.county_code")


def _fts_query(q):
    words = re.findall(r"[\w@.]+", q.lower())
    return " ".join(f'"{w}"*' for w in words[:8]) if words else None


def build_filter(p):
    where, params = [], []

    def multi(key):
        v = p.get(key)
        return [x for x in v.split(",") if x] if v else []

    q = (p.get("q") or "").strip()
    if q:
        fq = _fts_query(q)
        if fq:
            where.append("s.id IN (SELECT rowid FROM schools_fts WHERE schools_fts MATCH ?)")
            params.append(fq)
    for key, col in (("county", "s.county_code"), ("const", "s.subcounty_code"), ("status", "s.status"),
                     ("ownership", "s.ownership"), ("sponsor", "s.sponsor"), ("gender", "s.gender"),
                     ("boarding", "s.boarding"), ("setting", "s.setting"), ("enrich", "s.enrich_status")):
        vals = multi(key)
        if vals:
            clause = f"{col} IN ({','.join('?' * len([v for v in vals if v != 'none']))})" if any(
                v != "none" for v in vals) else None
            parts = [c for c in (clause, f"{col} IS NULL" if "none" in vals else None) if c]
            where.append("(" + " OR ".join(parts) + ")")
            params += [v for v in vals if v != "none"]
    faiths = multi("faith")
    if faiths:
        parts = []
        named = [f for f in faiths if f not in ("none", "any_religious")]
        if named:
            parts.append(f"s.faith IN ({','.join('?' * len(named))})")
            params += named
        if "any_religious" in faiths:
            parts.append("s.faith IS NOT NULL")
        if "none" in faiths:
            parts.append("s.faith IS NULL")
        where.append("(" + " OR ".join(parts) + ")")
    lv = multi("level")
    if lv:
        mask = 0
        for k in lv:
            mask |= levels.BY_KEY.get(k, 0)
        if "unknown" in lv:
            where.append(f"(s.levels & {mask} OR s.levels = 0)")
        else:
            where.append(f"s.levels & {mask}")
    grades = [int(g) for g in multi("grades") if re.fullmatch(r"-?\d+", g)]
    if grades:
        mask = levels.mask_for_grades(grades, primary_hosts_junior=p.get("jss", "1") == "1")
        where.append(f"s.levels & {mask}")
    if p.get("special") == "1":
        where.append("s.special_needs=1")
    for h in multi("has"):
        if h in ("email", "phone", "website", "leader", "postal_address"):
            where.append(f"s.{h} IS NOT NULL")
        elif h == "size":
            where.append("(s.students IS NOT NULL OR s.classrooms IS NOT NULL)")
        elif h in ("contact_form", "facebook", "instagram", "whatsapp"):
            if h == "whatsapp":
                where.append("EXISTS (SELECT 1 FROM contacts k WHERE k.school_id=s.id AND k.kind='phone' "
                             "AND k.label='WhatsApp' AND k.active=1)")
            else:
                where.append("EXISTS (SELECT 1 FROM contacts k WHERE k.school_id=s.id AND k.kind=? AND k.active=1)")
                params.append(h)
        elif h == "any_contact":
            where.append("(s.email IS NOT NULL OR s.phone IS NOT NULL OR s.website IS NOT NULL)")
    for h in multi("missing"):
        if h in ("email", "phone", "website", "leader"):
            where.append(f"s.{h} IS NULL")
        elif h == "any_contact":
            where.append("(s.email IS NULL AND s.phone IS NULL AND s.website IS NULL)")
    if p.get("starred") == "1":
        where.append("s.starred=1")
    if p.get("tag"):
        where.append("EXISTS (SELECT 1 FROM json_each(s.tags) WHERE json_each.value=?)")
        params.append(p["tag"])
    for key, expr in (("county_pop", "co.population"), ("const_pop", "sc.population"),
                      ("students", "s.students"), ("classrooms", "s.classrooms"),
                      ("size", "COALESCE(s.students, s.classrooms * 40)"), ("density", "s.pop_density")):
        if p.get(f"min_{key}"):
            where.append(f"{expr} >= ?")
            params.append(float(p[f"min_{key}"]))
        if p.get(f"max_{key}"):
            where.append(f"{expr} <= ?")
            params.append(float(p[f"max_{key}"]))
    if p.get("bbox"):
        try:
            w, s_, e, n = (float(x) for x in p["bbox"].split(","))
            where.append("s.lon BETWEEN ? AND ? AND s.lat BETWEEN ? AND ?")
            params += [w, e, s_, n]
        except ValueError:
            pass
    return ("WHERE " + " AND ".join(where)) if where else "", params


def _row(r):
    d = dict(r)
    for k in ("tags", "sources"):
        if k in d:
            d[k] = json.loads(d.get(k) or "[]")
    if "extra" in d:
        d["extra"] = json.loads(d.get("extra") or "{}")
    d["level_labels"] = levels.label_list(d.get("levels") or 0)
    return d


def api_schools(p):
    where, params = build_filter(p)
    key = p.get("sort") or ("name" if p.get("q") else "best")
    direction = "DESC" if p.get("dir") == "desc" else ("ASC" if p.get("dir") == "asc" else DEFAULT_DIR.get(key, "ASC"))
    order = ", ".join(c.replace("{dir}", direction) for c in SORTS.get(key, SORTS["name"]))
    limit = min(int(p.get("limit") or 50), 500)
    offset = int(p.get("offset") or 0)
    c = conn()
    total = c.execute(f"SELECT COUNT(*) {FROM} {where}", params).fetchone()[0]
    rows = c.execute(f"SELECT {LIST_COLS} {FROM} {where} ORDER BY {order}, s.id LIMIT ? OFFSET ?",
                     (*params, limit, offset)).fetchall()
    return {"total": total, "offset": offset, "rows": [_row(r) for r in rows]}


def api_points(p):
    """Every matching school as a compact [id, lat, lon, levels, status-code, has-contact] row for the map."""
    where, params = build_filter(p)
    status_code = {s: i for i, s in enumerate(db.STATUSES)}
    rows = conn().execute(
        f"SELECT s.id, s.lat, s.lon, s.levels, s.status, (s.email IS NOT NULL OR s.phone IS NOT NULL) AS reach "
        f"{FROM} {where} {'AND' if where else 'WHERE'} s.lat IS NOT NULL LIMIT 80000", params).fetchall()
    return {"points": [[r[0], round(r[1], 5), round(r[2], 5), r[3], status_code.get(r[4], 0), r[5]] for r in rows]}


def api_school(school_id):
    c = conn()
    r = c.execute(f"SELECT s.*, sc.population AS const_pop, sc.school_age AS const_school_age, "
                  f"co.population AS county_pop, co.school_age AS county_school_age {FROM} WHERE s.id=?",
                  (school_id,)).fetchone()
    if not r:
        return None
    s = _row(r)
    s["contacts"] = [dict(x) for x in c.execute(
        """SELECT * FROM contacts WHERE school_id=? ORDER BY active DESC, kind,
             CASE source WHEN 'manual' THEN 0 WHEN 'web' THEN 1 WHEN 'places' THEN 2 WHEN 'osm' THEN 3 ELSE 4 END,
             score DESC""", (school_id,))]
    s["shared_email_count"] = (c.execute(
        "SELECT COUNT(DISTINCT school_id) FROM contacts WHERE kind='email' AND active=1 AND value=?",
        (s["email"],)).fetchone()[0] if s["email"] else 0)
    s["activities"] = [dict(x) for x in c.execute(
        "SELECT * FROM activities WHERE school_id=? ORDER BY created_at DESC LIMIT 200", (school_id,))]
    s["nearby"] = [dict(x) for x in c.execute(
        """SELECT id, name, levels, status, email IS NOT NULL AS has_email,
             ((lat-?)*(lat-?) + (lon-?)*(lon-?)) AS d2 FROM schools
           WHERE id != ? AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? ORDER BY d2 LIMIT 8""",
        (s["lat"], s["lat"], s["lon"], s["lon"], school_id, s["lat"] - 0.03, s["lat"] + 0.03,
         s["lon"] - 0.03, s["lon"] + 0.03))] if s.get("lat") is not None else []
    for n in s["nearby"]:
        n["km"] = round((n.pop("d2") ** 0.5) * 111, 1)
        n["level_labels"] = levels.label_list(n["levels"])
    return s


def _log(c, school_id, kind, body):
    ts = db.now()
    c.execute("INSERT INTO activities(school_id, kind, body, created_at) VALUES (?,?,?,?)", (school_id, kind, body, ts))
    c.execute("UPDATE schools SET touched_at=? WHERE id=?", (ts, school_id))


STATUS_LABEL = {"new": "New", "queued": "Queued", "contacted": "Contacted", "replied": "Replied",
                "interested": "Interested", "visit": "Visit booked", "partner": "Partner",
                "not_interested": "Not interested", "do_not_contact": "Do not contact"}


def api_patch_school(school_id, body):
    c = conn()
    cur = c.execute("SELECT status FROM schools WHERE id=?", (school_id,)).fetchone()
    if not cur:
        return None
    sets = {}
    if body.get("status") in db.STATUSES and body["status"] != cur["status"]:
        sets["status"] = body["status"]
        _log(c, school_id, "status", f"{STATUS_LABEL[cur['status']]} → {STATUS_LABEL[body['status']]}")
    if "starred" in body:
        sets["starred"] = 1 if body["starred"] else 0
    if "tags" in body and isinstance(body["tags"], list):
        sets["tags"] = json.dumps(sorted({str(t).strip()[:40] for t in body["tags"] if str(t).strip()}))
    if "name" in body and str(body["name"]).strip():
        sets["name"] = str(body["name"]).strip()[:200]
    if "levels" in body and isinstance(body["levels"], list):
        mask = 0
        for k in body["levels"]:
            mask |= levels.BY_KEY.get(k, 0)
        sets["levels"] = mask
        lo, hi = levels.grades_for(mask)
        sets["grade_min"], sets["grade_max"] = lo, hi
        _log(c, school_id, "system", "Levels set to " + (", ".join(levels.label_list(mask)) or "unknown"))
    for k, allowed in (("ownership", ("public", "private", None)), ("gender", ("boys", "girls", "mixed", None)),
                       ("boarding", ("boarding", "day", "day_boarding", None))):
        if k in body and body[k] in allowed:
            sets[k] = body[k]
    for k in ("students", "teachers", "classrooms"):
        if k in body:
            try:
                sets[k] = int(body[k]) if body[k] not in (None, "") else None
            except (TypeError, ValueError):
                pass
    if sets:
        sets["updated_at"] = db.now()
        c.execute(f"UPDATE schools SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), school_id))
        db.index_one(c, school_id)
        c.commit()
    return api_school(school_id)


def api_bulk(body):
    ids = [int(i) for i in body.get("ids", [])][:5000]
    c = conn()
    n = 0
    for sid in ids:
        if body.get("status") in db.STATUSES:
            cur = c.execute("SELECT status FROM schools WHERE id=?", (sid,)).fetchone()
            if cur and cur["status"] != body["status"]:
                c.execute("UPDATE schools SET status=?, updated_at=? WHERE id=?", (body["status"], db.now(), sid))
                _log(c, sid, "status", f"{STATUS_LABEL[cur['status']]} → {STATUS_LABEL[body['status']]}")
                n += 1
        if body.get("tag"):
            row = c.execute("SELECT tags FROM schools WHERE id=?", (sid,)).fetchone()
            if row:
                tags = set(json.loads(row["tags"])) | {body["tag"].strip()[:40]}
                c.execute("UPDATE schools SET tags=? WHERE id=?", (json.dumps(sorted(tags)), sid))
                n += 1
        if "starred" in body:
            c.execute("UPDATE schools SET starred=? WHERE id=?", (1 if body["starred"] else 0, sid))
            n += 1
    c.commit()
    return {"updated": n}


def api_activity(school_id, body):
    kind = body.get("kind") if body.get("kind") in ("note", "call", "email", "meeting", "visit", "sms") else "note"
    text = str(body.get("body") or "").strip()[:5000]
    if not text:
        return {"error": "Write something to log first."}
    c = conn()
    _log(c, school_id, kind, text)
    c.commit()
    return api_school(school_id)


CONTACT_KINDS = ("email", "phone", "website", "contact_form", "contact_page", "facebook", "instagram", "youtube",
                 "x", "linkedin", "tiktok", "person", "address")


def api_add_contact(school_id, body):
    from . import extract
    kind = body.get("kind")
    value = str(body.get("value") or "").strip()
    if kind not in CONTACT_KINDS or not value:
        return {"error": "Choose a kind and enter a value."}
    if kind == "phone":
        value = extract.normalize_phone(value) or value
    if kind == "email":
        value = value.lower()
    c = conn()
    db.upsert_contact(c, school_id, kind, value, "manual", label=(body.get("label") or None), score=5)
    db.refresh_primary(c, school_id)
    db.index_one(c, school_id)
    _log(c, school_id, "system", f"Added {kind.replace('_', ' ')}: {value}")
    c.commit()
    return api_school(school_id)


def api_patch_contact(contact_id, body):
    c = conn()
    row = c.execute("SELECT school_id, kind, value FROM contacts WHERE id=?", (contact_id,)).fetchone()
    if not row:
        return None
    if "active" in body:
        c.execute("UPDATE contacts SET active=? WHERE id=?", (1 if body["active"] else 0, contact_id))
        _log(c, row["school_id"], "system",
             f"{'Restored' if body['active'] else 'Marked outdated'} {row['kind']}: {row['value']}")
    if body.get("primary"):
        c.execute("UPDATE contacts SET score=score+100, source='manual' WHERE id=?", (contact_id,))
        _log(c, row["school_id"], "system", f"Set main {row['kind']}: {row['value']}")
    db.refresh_primary(c, row["school_id"])
    db.index_one(c, row["school_id"])
    c.commit()
    return api_school(row["school_id"])


def api_refresh(school_id):
    from . import crawl
    c = conn()
    row = c.execute("SELECT website FROM schools WHERE id=?", (school_id,)).fetchone()
    if not row or not row["website"]:
        return {"error": "This school has no website on file. Add one under Contacts, then check it."}
    res = crawl.crawl_site(row["website"])
    with _refresh_lock:
        crawl.save(c, school_id, res)
        _log(c, school_id, "system", f"Checked website: {res['status']}"
             + (f", found {len(res.get('emails', {}))} emails and {len(res.get('phones', {}))} phones"
                if res["status"] == "ok" else f" ({res.get('error')})"))
        c.commit()
    return api_school(school_id)


def api_summary():
    """Dashboard numbers, as a few single-pass aggregates (each query is a round trip when hosted)."""
    c = conn()
    a = dict(c.execute(
        """SELECT COUNT(*) AS schools,
             SUM(levels & 1 > 0) AS l_ecde, SUM(levels & 2 > 0) AS l_primary, SUM(levels & 4 > 0) AS l_junior,
             SUM(levels & 8 > 0) AS l_senior, SUM(levels & 256 > 0) AS l_nonformal, SUM(levels & 16 > 0) AS l_tvet,
             SUM(levels & 32 > 0) AS l_ttc, SUM(levels & 64 > 0) AS l_university, SUM(levels & 128 > 0) AS l_adult,
             SUM(levels = 0) AS l_unknown,
             SUM(ownership='public') AS public, SUM(ownership='private') AS private,
             SUM(email IS NOT NULL) AS with_email, SUM(phone IS NOT NULL) AS with_phone,
             SUM(website IS NOT NULL) AS with_website, SUM(leader IS NOT NULL) AS with_leader,
             SUM(postal_address IS NOT NULL) AS with_address,
             SUM(email IS NOT NULL OR phone IS NOT NULL) AS reachable,
             SUM(website IS NOT NULL AND enriched_at IS NULL) AS never_checked,
             SUM(setting='urban') AS urban, SUM(setting='peri_urban') AS peri_urban, SUM(setting='rural') AS rural,
             SUM(students IS NOT NULL) AS with_students, SUM(classrooms IS NOT NULL) AS with_classrooms,
             SUM(osm_id IS NOT NULL) AS src_osm, SUM(moe_keys != '[]') AS src_moe,
             SUM(status NOT IN ('new','queued')) AS engaged
           FROM schools""").fetchone())
    a = {k: (v or 0) for k, v in a.items()}
    counties = [dict(r) for r in c.execute(
        """SELECT a.code, a.name, a.population, a.school_age, a.area_sqkm,
             COUNT(s.id) AS schools, SUM(s.levels & 2 > 0) AS primary_n, SUM(s.levels & 8 > 0) AS senior_n,
             SUM(s.email IS NOT NULL OR s.phone IS NOT NULL) AS reachable,
             SUM(s.status NOT IN ('new','queued')) AS engaged, SUM(s.status='partner') AS partners
           FROM areas a LEFT JOIN schools s ON s.county_code=a.code WHERE a.kind='county'
           GROUP BY a.code ORDER BY a.population DESC""")]
    return {
        **a,
        "by_status": {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM schools GROUP BY status")},
        "faiths": [dict(r) for r in c.execute(
            "SELECT faith AS name, COUNT(*) AS n FROM schools WHERE faith IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")],
        "counties": counties,
        "population": sum(x["population"] or 0 for x in counties),
        "school_age": sum(x["school_age"] or 0 for x in counties),
        "recent": [dict(r) for r in c.execute(
            """SELECT a.kind, a.body, a.created_at, s.id AS school_id, s.name AS school_name, s.county
               FROM activities a JOIN schools s ON s.id=a.school_id WHERE a.kind != 'system'
               ORDER BY a.created_at DESC LIMIT 10""")],
        "runs": [dict(r) for r in c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 12")],
        "places_enabled": bool(config.GOOGLE_PLACES_API_KEY),
        "brave_enabled": bool(config.BRAVE_API_KEY),
    }


def api_facets():
    c = conn()
    return {
        "counties": [dict(r) for r in c.execute(
            "SELECT code, name, population, school_age FROM areas WHERE kind='county' ORDER BY name")],
        "constituencies": [dict(r) for r in c.execute(
            "SELECT code, name, county_code, population FROM areas WHERE kind='subcounty' ORDER BY name")],
        "levels": [{"key": k, "label": label, "grades": [g0, g1]} for _, k, label, g0, g1 in levels.LEVELS],
        "faiths": [dict(value=r[0], n=r[1]) for r in c.execute(
            "SELECT faith, COUNT(*) FROM schools WHERE faith IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")],
        "sponsors": [dict(value=k, label=v) for k, v in levels.SPONSOR_LABEL.items()],
        "statuses": [dict(value=s, label=STATUS_LABEL[s]) for s in db.STATUSES],
        "tags": [r[0] for r in c.execute(
            "SELECT DISTINCT json_each.value FROM schools, json_each(schools.tags) ORDER BY 1 LIMIT 200")],
    }


def api_areas(p):
    kind = "subcounty" if p.get("kind") == "const" else "county"
    where, params = ["a.kind=?"], [kind]
    if p.get("county"):
        where.append("a.county_code=?")
        params.append(p["county"])
    key = "s.subcounty_code" if kind == "subcounty" else "s.county_code"
    rows = conn().execute(
        f"""SELECT a.code, a.name, a.county_code, a.population, a.school_age, a.area_sqkm,
              (SELECT name FROM areas c WHERE c.code=a.county_code) AS county,
              COUNT(s.id) AS schools, SUM(s.levels & 1 > 0) AS ecde_n, SUM(s.levels & 2 > 0) AS primary_n,
              SUM(s.levels & 8 > 0) AS senior_n, SUM(s.levels & (16|32|64) > 0) AS post_n,
              SUM(s.ownership='private') AS private_n,
              SUM(s.email IS NOT NULL) AS emails, SUM(s.phone IS NOT NULL) AS phones,
              SUM(s.status NOT IN ('new','queued')) AS engaged, SUM(s.status='partner') AS partners
            FROM areas a LEFT JOIN schools s ON {key}=a.code
            WHERE {' AND '.join(where)} GROUP BY a.code ORDER BY a.population DESC""", params).fetchall()
    return {"rows": [dict(r) for r in rows]}


def api_geo():
    c = conn()
    feats = [{"type": "Feature", "id": r["code"], "properties": {"name": r["name"]},
              "geometry": json.loads(r["geometry"])}
             for r in c.execute("SELECT code, name, geometry FROM areas WHERE kind='county'")]
    return {"type": "FeatureCollection", "features": feats}


def api_pipeline(p):
    where, params = build_filter({k: v for k, v in p.items() if k != "status"})
    out = {}
    c = conn()
    for s in db.STATUSES:
        w = (where + " AND " if where else "WHERE ") + "s.status=?"
        n = c.execute(f"SELECT COUNT(*) {FROM} {w}", (*params, s)).fetchone()[0]
        order = ("s.touched_at DESC NULLS LAST" if s != "new" else
                 "s.starred DESC, (s.leader IS NOT NULL) DESC, (s.email IS NOT NULL) DESC, (s.phone IS NOT NULL) DESC")
        rows = c.execute(f"SELECT {LIST_COLS} {FROM} {w} ORDER BY {order} LIMIT 40", (*params, s)).fetchall()
        out[s] = {"total": n, "rows": [_row(r) for r in rows]}
    return out


EXPORT_COLS = ["id", "name", "levels", "grades", "ownership", "sponsor", "faith", "gender", "boarding",
               "leader", "email", "phone", "website", "address", "postal_address", "county", "constituency", "town",
               "location", "sublocation", "lat", "lon", "setting", "students", "classrooms", "teachers",
               "county_population", "constituency_population", "status", "tags", "starred", "all_emails",
               "all_phones", "facebook", "whatsapp", "website_checked", "sources"]


def api_export(p):
    where, params = build_filter(p)
    rows = conn().execute(
        f"""SELECT s.*, co.population AS county_population, sc.population AS constituency_population,
               (SELECT group_concat(value, '; ') FROM contacts WHERE school_id=s.id AND kind='email' AND active=1) AS all_emails,
               (SELECT group_concat(value, '; ') FROM contacts WHERE school_id=s.id AND kind='phone' AND active=1
                  AND COALESCE(label,'')!='fax') AS all_phones,
               (SELECT value FROM contacts WHERE school_id=s.id AND kind='facebook' AND active=1 LIMIT 1) AS facebook,
               (SELECT value FROM contacts WHERE school_id=s.id AND kind='phone' AND label='WhatsApp' AND active=1 LIMIT 1) AS whatsapp
            {FROM} {where} ORDER BY s.county, s.subcounty, s.name""", params).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPORT_COLS)
    from datetime import datetime, timezone
    for r in rows:
        d = dict(r)
        d["levels"] = "; ".join(levels.label_list(d["levels"] or 0))
        d["grades"] = (f"{levels.GRADE_LABELS.get(d['grade_min'])} – {levels.GRADE_LABELS.get(d['grade_max'])}"
                       if d.get("grade_min") is not None else "")
        d["constituency"] = d.get("subcounty")
        d["website_checked"] = (datetime.fromtimestamp(d["enriched_at"], timezone.utc).strftime("%Y-%m-%d")
                                if d.get("enriched_at") else "")
        d["tags"] = ", ".join(json.loads(d.get("tags") or "[]"))
        d["sources"] = ", ".join(json.loads(d.get("sources") or "[]"))
        w.writerow([d.get(k, "") if d.get(k) is not None else "" for k in EXPORT_COLS])
    return buf.getvalue()


# ------------------------------------------------------------------ access

COOKIE = "ksd_session"


def auth_required():
    return bool(config.APP_PASSWORD) or config.ON_VERCEL


def _token():
    return hmac.new(config.SESSION_SECRET.encode(), b"kenya-schools-directory/v1", hashlib.sha256).hexdigest()


def setup_problem():
    missing = []
    if config.ON_VERCEL and not config.APP_PASSWORD:
        missing.append("APP_PASSWORD")
    if config.ON_VERCEL and not (config.TURSO_URL and config.TURSO_TOKEN):
        missing += [k for k, v in (("TURSO_DATABASE_URL", config.TURSO_URL), ("TURSO_AUTH_TOKEN", config.TURSO_TOKEN))
                    if not v]
    return missing


class Handler(BaseHTTPRequestHandler):
    server_version = "KenyaSchoolsDirectory/1.0"

    def log_message(self, fmt, *args):
        first = str(args[0]) if args else ""
        if "/api/" in first and len(args) > 1 and not str(args[1]).startswith("2"):
            log("  " + fmt % args)

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        data = body if isinstance(body, bytes) else (
            body.encode() if isinstance(body, str) else json.dumps(body, default=str).encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except ValueError:
            return {}

    def _params(self):
        return {k: v[-1] for k, v in parse_qs(urlsplit(self.path).query).items()}

    def _authed(self):
        if not auth_required():
            return True
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE and config.SESSION_SECRET and hmac.compare_digest(v, _token()):
                return True
        return False

    def _login(self, method):
        if method != "POST":
            return self._send(405, {"error": "method"})
        pw = str(self._body().get("password") or "")
        if not config.APP_PASSWORD or not hmac.compare_digest(pw.encode(), config.APP_PASSWORD.encode()):
            time.sleep(0.8)  # slow down guessing
            return self._send(401, {"error": "That password isn't right."})
        secure = "; Secure" if config.ON_VERCEL else ""
        return self._send(200, {"ok": True}, headers={
            "Set-Cookie": f"{COOKIE}={_token()}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000{secure}"})

    def _route(self, method):
        parts = urlsplit(self.path)
        path = parts.path
        q = parse_qs(parts.query)
        if "__p" in q:  # Vercel rewrites /api/* to /api/index?__p=<rest>
            rest = q.pop("__p")[-1]
            path = "/api/" + rest.lstrip("/")
            self.path = path + ("?" + urlencode({k: v[-1] for k, v in q.items()}) if q else "")
        try:
            if path.startswith("/api/"):
                sub = path[5:]
                if sub == "me":
                    return self._send(200, {"auth": auth_required(), "signed_in": self._authed(),
                                            "missing": setup_problem()})
                if sub == "login":
                    return self._login(method)
                if sub == "logout":
                    return self._send(200, {"ok": True}, headers={"Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0"})
                missing = setup_problem()
                if missing:
                    return self._send(503, {"error": "not_configured", "missing": missing})
                if not self._authed():
                    return self._send(401, {"error": "sign_in"})
                return self._api(method, sub)
            if method != "GET":
                return self._send(405, {"error": "method"})
            return self._static(path)
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": str(e)})

    def _api(self, method, path):
        p = self._params()
        get = method == "GET"
        if get and path == "summary":
            return self._send(200, api_summary())
        if get and path == "facets":
            return self._send(200, api_facets())
        if get and path == "schools":
            return self._send(200, api_schools(p))
        if get and path == "points":
            return self._send(200, api_points(p))
        if get and path == "areas":
            return self._send(200, api_areas(p))
        if get and path == "geo/counties":
            return self._send(200, api_geo())
        if get and path == "pipeline":
            return self._send(200, api_pipeline(p))
        if get and path == "export.csv":
            return self._send(200, api_export(p), "text/csv; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="kenya-schools.csv"'})
        if method == "POST" and path == "bulk":
            return self._send(200, api_bulk(self._body()))
        m = re.fullmatch(r"schools/(\d+)(?:/(\w+))?", path)
        if m:
            sid, action = int(m.group(1)), m.group(2)
            if get and not action:
                s = api_school(sid)
                return self._send(200 if s else 404, s or {"error": "not found"})
            if method == "PATCH" and not action:
                s = api_patch_school(sid, self._body())
                return self._send(200 if s else 404, s or {"error": "not found"})
            if method == "POST" and action == "activities":
                return self._send(200, api_activity(sid, self._body()))
            if method == "POST" and action == "contacts":
                return self._send(200, api_add_contact(sid, self._body()))
            if method == "POST" and action == "refresh":
                return self._send(200, api_refresh(sid))
        m = re.fullmatch(r"contacts/(\d+)", path)
        if m and method == "PATCH":
            s = api_patch_contact(int(m.group(1)), self._body())
            return self._send(200 if s else 404, s or {"error": "not found"})
        return self._send(404, {"error": "no such endpoint"})

    def _static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        target = (config.UI_DIR / path.lstrip("/")).resolve()
        if not str(target).startswith(str(config.UI_DIR.resolve())) or not target.is_file():
            target = config.UI_DIR / "index.html"
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def do_GET(self):
        self._route("GET")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_POST(self):
        self._route("POST")

    def do_PATCH(self):
        self._route("PATCH")

    def do_PUT(self):
        self._route("PUT")


def serve(host="127.0.0.1", port=8130):
    if host not in ("127.0.0.1", "localhost") and not config.APP_PASSWORD:
        raise SystemExit("Set APP_PASSWORD before serving the CRM beyond this computer.")
    db.connect().close()
    httpd = ThreadingHTTPServer((host, port), Handler)
    log(f"Kenya Schools Directory running at http://{host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
