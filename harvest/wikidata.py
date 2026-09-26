"""Wikidata: official websites for Kenyan schools, colleges and universities.

Two lookups: every school the map links to a Wikidata item (the OSM `wikidata`
tag), and every educational institution Wikidata places in Kenya, matched to a
directory school by name and location.
"""

import json
import re
import urllib.parse

from . import config, db, levels, net, osm
from .net import log

TYPES = ("Q3914 Q159334 Q9842 Q3918 Q189004 Q9826 Q269770 Q38723 Q902104 Q1244442 Q875538 Q23002054 "
         "Q1664720 Q2143781 Q7894959 Q15936437 Q5341295")


def _sparql(query):
    url = config.WIKIDATA_SPARQL + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    data = net.request_json(url, headers={"Accept": "application/sparql-results+json"}, timeout=120)
    return data["results"]["bindings"]


def _val(b, k):
    return (b.get(k) or {}).get("value")


def ingest(conn):
    ts = db.now()
    stats = {"linked": 0, "matched": 0, "websites": 0}
    # 1. Items the map already links to.
    linked = {r["wikidata"]: r["id"] for r in conn.execute(
        "SELECT id, wikidata FROM schools WHERE wikidata LIKE 'Q%'")}
    ids = sorted(linked)
    for i in range(0, len(ids), 150):
        chunk = " ".join(f"wd:{q}" for q in ids[i:i + 150] if re.fullmatch(r"Q\d+", q))
        if not chunk:
            continue
        rows = _sparql(f"SELECT ?s ?website WHERE {{ VALUES ?s {{ {chunk} }} ?s wdt:P856 ?website. }}")
        for b in rows:
            qid = _val(b, "s").rsplit("/", 1)[-1]
            sid = linked.get(qid)
            if sid and _add_site(conn, sid, _val(b, "website"), qid, ts):
                stats["websites"] += 1
        stats["linked"] += len(ids[i:i + 150])
    # 2. Every educational institution in Kenya.
    values = " ".join(f"wd:{t}" for t in TYPES.split())
    rows = _sparql(f"""SELECT ?s ?sLabel ?website ?coord WHERE {{
        VALUES ?t {{ {values} }} ?s wdt:P31 ?t; wdt:P17 wd:Q114; wdt:P856 ?website.
        OPTIONAL {{ ?s wdt:P625 ?coord }}
        SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }} }}""")
    index = osm.SchoolIndex(conn)
    for b in rows:
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", _val(b, "coord") or "")
        qid = _val(b, "s").rsplit("/", 1)[-1]
        if qid in linked or not m:
            continue
        rec = {"raw_name": _val(b, "sLabel") or "", "lat": float(m.group(2)), "lon": float(m.group(1)),
               "levels": levels.levels_from_name(_val(b, "sLabel") or "")}
        hit = osm.best_match(index, rec)
        if hit:
            conn.execute("UPDATE schools SET wikidata=COALESCE(wikidata, ?) WHERE id=?", (qid, hit["id"]))
            stats["matched"] += 1
            if _add_site(conn, hit["id"], _val(b, "website"), qid, ts):
                stats["websites"] += 1
    conn.commit()
    log(f"  {stats['websites']} websites from Wikidata")
    return stats


def _add_site(conn, school_id, website, qid, ts):
    added = False
    for kind, value, label in osm.url_contacts(website):
        db.upsert_contact(conn, school_id, kind, value, "wikidata", label=label,
                          source_url=f"https://www.wikidata.org/wiki/{qid}", score=2, ts=ts)
        added = added or kind == "website"
    cur = conn.execute("SELECT sources FROM schools WHERE id=?", (school_id,)).fetchone()
    conn.execute("UPDATE schools SET sources=? WHERE id=?", (db.add_sources(cur["sources"], "wikidata"), school_id))
    db.refresh_primary(conn, school_id)
    return added
