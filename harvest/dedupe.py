"""Fold duplicate school records together.

Duplicates come from the map: the same school drawn twice (a point and its
compound outline), or a map school that sits further from its Ministry record
than the osm step's matching allows. Two Ministry records are never folded
here; the moe step already decided those are separate schools.
"""

import json

from . import db, levels, osm
from .net import log

BASIC = levels.ECDE | levels.PRIMARY | levels.JUNIOR | levels.NONFORMAL


def _compatible(a, b):
    if not a or not b or a & b:
        return True
    return bool(a & BASIC and b & BASIC)


def run(conn):
    index = osm.SchoolIndex(conn)
    info = {r["id"]: dict(r) for r in conn.execute("SELECT id, moe_keys, levels, status FROM schools")}
    gone = set()
    merged = 0
    for sid, r in list(index.rows.items()):
        if sid in gone:
            continue
        for other, d in index.near(r["lat"], r["lon"], 1.5):
            oid = other["id"]
            if oid == sid or oid in gone:
                continue
            a, b = info[sid], info[oid]
            if a["moe_keys"] != "[]" and b["moe_keys"] != "[]":
                continue
            if not _compatible(a["levels"], b["levels"]):
                continue
            score = osm.name_score(r["tokens"], other["tokens"])
            if not (score >= 0.95 and d <= 1.5 or score >= 0.75 and d <= 0.4):
                continue
            keep, drop = (sid, oid) if (a["moe_keys"] != "[]" or (b["moe_keys"] == "[]" and sid < oid)) else (oid, sid)
            db.merge_schools(conn, keep, drop)
            info[keep]["levels"] = (info[keep]["levels"] or 0) | (info[drop]["levels"] or 0)
            info[keep]["moe_keys"] = json.dumps(sorted(set(json.loads(info[keep]["moe_keys"]))
                                                       | set(json.loads(info[drop]["moe_keys"]))))
            gone.add(drop)
            merged += 1
            if drop == sid:
                break
    merged += fold_list_only(conn)
    conn.commit()
    if merged:
        log(f"  folded {merged:,} duplicate records")
    return {"merged": merged}


def fold_list_only(conn):
    """Schools known only from a county list (no map position) that are a spelling
    variant of a mapped school in the same county: fold them into that school."""
    by_county = {}
    for r in conn.execute("SELECT id, name, county_code FROM schools WHERE levels & 8 AND lat IS NOT NULL"):
        by_county.setdefault(r["county_code"], []).append((r["id"], levels.tokens(r["name"])))
    n = 0
    for r in conn.execute("SELECT id, name, county_code FROM schools WHERE lat IS NULL AND sources LIKE '%teacher%'").fetchall():
        toks = levels.tokens(r["name"])
        best = None
        for sid, t in by_county.get(r["county_code"], ()):
            sc = osm.name_score(toks, t)
            if sc >= 0.85 and (best is None or sc > best[0]):
                best = (sc, sid)
        if best:
            db.merge_schools(conn, best[1], r["id"])
            n += 1
    return n
