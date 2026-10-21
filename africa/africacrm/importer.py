"""Country data files -> the CRM database.

Every country ships one JSONL file in the shared format (see DATA-FORMAT.md): one
institution per line, every email / phone / official with the public page it came
from. `load` upserts a file into the CRM and keeps the outreach history already there
(stages, notes, sequences and contacts you added by hand).
"""

import hashlib
import json
from collections import Counter
from pathlib import Path

from . import config, db, levels
from .countries import COUNTRIES, get

VALID_OWNERSHIP = {"government", "government_assisted", "private", "community", "mission", "ngo"}
VALID_KIND = {"school", "office", "secretariat", "association", "ngo"}
VALID_CONF = {"high", "medium", "low"}


def default_dataset(code):
    """dataset/<slug>-schools.jsonl if it's there, else the project folder's copy."""
    c = get(code)
    name = f"{c.slug}-schools.jsonl"
    for p in (config.DATASET_DIR / name, config.PROJECT_FILES / f"{c.slug}-schools" / name):
        if p.is_file():
            return p
    return None


def _url(u):
    u = (u or "").strip() if isinstance(u, str) else ""
    return u if u.startswith(("http://", "https://")) else None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def normalize(rec, country):
    """One record in the shared format -> what `load` stores, with everything unverifiable dropped."""
    c = get(country)
    name = " ".join(str(rec.get("name") or "").split())
    sources = [u for u in (_url(s) for s in rec.get("sources") or []) if u]
    lv = levels.clean_keys(rec.get("levels")) or levels.levels_from_name(name, c.name_rules)
    kind = rec.get("kind") if rec.get("kind") in VALID_KIND else "school"
    if kind != "school" and "admin" not in lv:
        lv.append("admin")
    area = rec.get("area") or rec.get("subcounty") or rec.get("chiefdom") or rec.get("constituency")
    district = c.canonical_district(rec.get("district")) or c.district_from_text(
        rec.get("town"), rec.get("address"), area)
    emails, seen = [], set()

    def add_email(addr, src, conf, person=None, role=None, seen_on=None):
        if not addr or not src or addr in seen:
            return  # an address without the page it came from can't be checked, so it's left out
        seen.add(addr)
        emails.append({"email": addr, "source_url": src, "confidence": conf if conf in VALID_CONF else "medium",
                       "seen": seen_on, "person": person, "role": role})

    for e in rec.get("emails") or []:
        if isinstance(e, str):
            e = {"email": e}
        add_email(levels.clean_email(e.get("email")), _url(e.get("source_url")) or (sources[0] if len(sources) == 1
                  else None), e.get("confidence"), e.get("person"), e.get("role"), e.get("seen"))
    phones, pseen = [], set()

    def add_phone(num, src):
        if num and num not in pseen:
            pseen.add(num)
            phones.append({"phone": num, "source_url": src})

    for p in rec.get("phones") or []:
        if isinstance(p, str):
            p = {"phone": p}
        add_phone(c.clean_phone(p.get("phone")), _url(p.get("source_url")) or (sources[0] if sources else None))
    officials = []
    for o in rec.get("officials") or []:
        if not isinstance(o, dict) or not (o.get("name") or "").strip():
            continue
        src = _url(o.get("source_url")) or (sources[0] if len(sources) == 1 else None)
        off = {"name": " ".join(o["name"].split()), "role": (o.get("role") or "").strip() or None,
               "email": levels.clean_email(o.get("email")) if src else None,
               "phone": c.clean_phone(o.get("phone")), "source_url": src}
        officials.append(off)
        if off["email"] in seen:
            for e in emails:
                if e["email"] == off["email"] and not e["person"]:
                    e["person"], e["role"] = off["name"], off["role"]
        else:
            add_email(off["email"], src, "medium", off["name"], off["role"])
        add_phone(off["phone"], src)
    sources += [e["source_url"] for e in emails]
    own = rec.get("ownership") if rec.get("ownership") in VALID_OWNERSHIP else None
    denom = rec.get("denomination") or levels.faith_from_name(name)
    if not own and denom:
        own = "mission"
    province = c.province(district) or rec.get("province") or rec.get("region") or None
    out = {
        "id": str(rec.get("id") or "").strip() or None, "country": c.code,
        "name": name, "kind": kind, "levels": lv, "province": province, "district": district, "area": area or None,
        "town": rec.get("town") or None, "address": rec.get("address") or None, "ownership": own or "unknown",
        "denomination": denom, "website": _url(rec.get("website")), "emails": emails, "phones": phones,
        "officials": officials, "emis_code": str(rec["emis_code"]).strip() if rec.get("emis_code") else None,
        "lat": _num(rec.get("lat")), "lon": _num(rec.get("lon")),
        "students": int(rec["students"]) if _num(rec.get("students")) else None,
        "setting": rec.get("setting") if rec.get("setting") in ("urban", "peri_urban", "rural") else None,
        "gender": rec.get("gender") if rec.get("gender") in ("boys", "girls", "mixed") else None,
        "boarding": rec.get("boarding") if rec.get("boarding") in ("boarding", "day", "day_boarding") else None,
        "sources": sorted(set(sources)), "notes": rec.get("notes") or None,
    }
    if not out["id"]:
        out["id"] = hashlib.sha1(f"{levels.norm_name(name)}|{district}|{out['town']}|{out['emis_code']}"
                                 .encode()).hexdigest()[:12]
    return out


SCHOOL_COLS = ("name", "norm", "kind", "levels", "ownership", "denomination", "province", "district", "area", "town",
               "address", "lat", "lon", "emis_code", "students", "setting", "gender", "boarding", "notes")


def load_records(conn, records, country, source="research", ts=None):
    """Upsert normalized records. Returns {added, updated} and the ref -> school id map."""
    t = ts or db.now()
    stats, ids = Counter(), {}
    for r in records:
        if not r["name"]:
            stats["skipped"] += 1
            continue
        vals = {k: r.get(k) for k in SCHOOL_COLS}
        vals["norm"] = levels.norm_name(r["name"])
        vals["levels"] = levels.mask(r["levels"])
        row = conn.execute("SELECT id, sources FROM schools WHERE country=? AND ref=?", (country, r["id"])).fetchone()
        if row:
            sid = row["id"]
            sets = ", ".join(f"{k}=COALESCE(?, {k})" for k in vals)
            conn.execute(f"UPDATE schools SET {sets}, sources=?, updated_at=? WHERE id=?",
                         (*vals.values(), db.add_sources(row["sources"], *r["sources"]), t, sid))
            stats["updated"] += 1
        else:
            cols = ", ".join(vals)
            cur = conn.execute(
                f"INSERT INTO schools(country, ref, {cols}, sources, created_at, updated_at) "
                f"VALUES (?, ?, {', '.join('?' for _ in vals)}, ?, ?, ?)",
                (country, r["id"], *vals.values(), json.dumps(r["sources"]), t, t))
            sid = cur.lastrowid
            stats["added"] += 1
        ids[r["id"]] = sid
        for e in r["emails"]:
            db.upsert_contact(conn, sid, "email", e["email"], source, e.get("person"), e.get("role"),
                              e["source_url"], e["confidence"], t, e.get("active", 1))
        for p in r["phones"]:
            db.upsert_contact(conn, sid, "phone", p["phone"], source, source_url=p.get("source_url"), ts=t,
                              active=p.get("active", 1))
        for o in r["officials"]:
            db.upsert_contact(conn, sid, "person", o["name"], source, o["name"], o.get("role"), o.get("source_url"),
                              ts=t)
        if r.get("website"):
            db.upsert_contact(conn, sid, "website", r["website"], source, ts=t)
        db.refresh_primary(conn, sid, country)
    for d in {r["district"] for r in records if r["district"]}:
        prov = next((r["province"] for r in records if r["district"] == d and r["province"]), None)
        conn.execute("INSERT INTO regions(country, district, province) VALUES (?,?,?) "
                     "ON CONFLICT(country, district) DO UPDATE SET province=COALESCE(regions.province, "
                     "excluded.province)", (country, d, prov))
    conn.commit()
    return dict(stats), ids


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    yield rec


def load(conn, path, country=None):
    """Load one country's file. The country comes from the argument, else each record's "country"."""
    by_country = {}
    for rec in read_jsonl(path):
        code = (country or rec.get("country") or "").upper()
        if code not in COUNTRIES:
            raise ValueError(f"{path}: say which country this file is (--country), or add \"country\" to each row.")
        by_country.setdefault(code, []).append(normalize(rec, code))
    out = {}
    for code, recs in by_country.items():
        out[code], _ = load_records(conn, recs, code)
    return out


def load_all(conn):
    """Every country whose data file can be found."""
    out = {}
    for code in COUNTRIES:
        p = default_dataset(code)
        if p:
            out[code] = {"file": str(p), **load(conn, p, code).get(code, {})}
        else:
            out[code] = {"file": None, "note": f"no {get(code).slug}-schools.jsonl in dataset/ or the project folder"}
    return out


def summarize(conn, country):
    q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    return {"institutions": q("SELECT COUNT(*) FROM schools WHERE country=?", country),
            "with_email": q("SELECT COUNT(*) FROM schools WHERE country=? AND email IS NOT NULL", country),
            "with_phone": q("SELECT COUNT(*) FROM schools WHERE country=? AND phone IS NOT NULL", country),
            "with_mobile": q("SELECT COUNT(*) FROM schools WHERE country=? AND mobile IS NOT NULL", country)}


def write_jsonl(records, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
