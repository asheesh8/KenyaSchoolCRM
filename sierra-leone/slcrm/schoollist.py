"""The Ministry's EMIS school lists (2016 and 2017 PDFs on mbsse.gov.sl).

Each PDF lists every school in the country with its EMIS code, level, council, chiefdom,
name, town, a phone number (usually the head teacher's) and owner. No emails. The numbers
date from 2016/17, so some will be stale. The research sandbox could only read the first
two districts of these files; run this on your own computer to read all of them:

    python3 -m slcrm schoollist

It adds the phones to the CRM database and writes data/schoollist.jsonl (research-file
format, see dataset/SCHEMA.md), which can be shared back and merged into the dataset.
Text extraction uses `pdftotext` (poppler: `brew install poppler`, `apt install
poppler-utils`) or, if that's missing, the pypdf library.
"""

import json
import re
import shutil
import subprocess

from . import config, db, levels
from .net import log, request

URLS = ["https://mbsse.gov.sl/wp-content/uploads/2020/03/2017-School-List.pdf",
        "https://mbsse.gov.sl/wp-content/uploads/2020/03/2016-School-List.pdf"]

LEVEL_WORDS = {"preschool": "pre_primary", "pre-school": "pre_primary", "pre-primary": "pre_primary",
               "primary": "primary", "jss": "junior_secondary", "sss": "senior_secondary",
               "tvet": "tvet", "technical": "tvet", "vocational": "tvet"}
OWNERS = {"government": "government", "mission": "mission", "community": "community", "private": "private",
          "ngo": "ngo", "gov't assisted": "government_assisted", "government assisted": "government_assisted"}
_ROW = re.compile(r"^\s*(\d{8,10})\s+(pre-?school|pre-?primary|primary|jss|sss|tvet|technical|vocational)\b\s*(.*)$",
                  re.I)
_OWNER = re.compile(r"\s+(gov't assisted|government assisted|government|mission|community|private|ngo)\s*$", re.I)
_PHONE = re.compile(r"(?:\+?232[\s-]?)?\b0?\d{2}[\s-]?\d{3}[\s-]?\d{3}\b")
_REGION = re.compile(r"^(north[\s-]?west|east|north|south|west(?:ern)?)\b\s*", re.I)
_COUNCIL = re.compile(r"^(.*?\b(?:dc|district council|city council|municipal council|rural district)\b)\s*(\d{1,3})?\s*",
                      re.I)


def pdf_text(path):
    if shutil.which("pdftotext"):
        return subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True,
                              check=True).stdout
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit("Needs pdftotext (poppler) or pypdf: brew install poppler / apt install poppler-utils / "
                         "pip install pypdf")
    return "\n".join(p.extract_text(extraction_mode="layout") or "" for p in PdfReader(str(path)).pages)


def parse_line(line):
    """One table row -> dict, or None for headers, page furniture and wrapped fragments."""
    m = _ROW.match(line)
    if not m:
        return None
    emis, level, rest = m.group(1), LEVEL_WORDS[m.group(2).lower().replace(" ", "")], m.group(3).rstrip()
    owner = None
    om = _OWNER.search(rest)
    if om:
        owner = OWNERS.get(om.group(1).lower())
        rest = rest[:om.start()]
    phone = None
    pm = list(_PHONE.finditer(rest))
    if pm and len(re.sub(r"\D", "", pm[-1].group())) >= 8:
        phone = levels.clean_phone(pm[-1].group())
        rest = rest[:pm[-1].start()]
    rm = _REGION.match(rest)
    if rm:
        rest = rest[rm.end():]
    council = chiefdom = None
    cm = _COUNCIL.match(rest)
    if cm:
        council, chiefdom, rest = cm.group(1).strip(), cm.group(2), rest[cm.end():]
    # With -layout, name and town are separated by a wide gap; otherwise the town stays in the name.
    cells = [c for c in re.split(r"\s{2,}", rest.strip()) if c]
    if not cells:
        return None
    name, town = (" ".join(cells[:-1]), cells[-1]) if len(cells) > 1 else (cells[0], None)
    district = levels.district_from_text(council, town)
    if council and re.search(r"freetown|western area urban", council, re.I):
        district = "Western Area Urban"
    elif council and re.search(r"western area rural|waterloo", council, re.I):
        district = "Western Area Rural"
    return {"emis": emis, "level": level, "name": " ".join(name.split()), "town": town, "council": council,
            "chiefdom_no": chiefdom, "district": district, "phone": phone, "owner": owner}


def parse(text):
    return [r for r in (parse_line(l) for l in text.splitlines()) if r]


def record(r, url):
    """A parsed row in the research-file format, so it can be merged with the rest of the dataset."""
    faith = levels.faith_from_name(r["name"])
    return {"name": r["name"], "kind": "school", "levels": [r["level"]], "district": r["district"], "chiefdom": None,
            "town": r["town"], "address": None, "ownership": r["owner"] or ("mission" if faith else "unknown"),
            "denomination": faith, "website": None, "emails": [],
            "phones": [{"phone": r["phone"], "source_url": url}] if r["phone"] else [], "officials": [],
            "emis_code": r["emis"], "lat": None, "lon": None, "sources": [url],
            "notes": f"MBSSE EMIS school list; council {r['council']}" if r["council"] else "MBSSE EMIS school list",
            "worker": "schoollist"}


def _find(conn, r):
    for c in conn.execute("SELECT * FROM schools WHERE emis_code=?", (r["emis"],)).fetchall():
        if levels.similar(c["name"], r["name"]) >= .6:
            return c
    mk = levels.merge_key(r["name"])
    for c in conn.execute("SELECT * FROM schools WHERE norm=? AND district IS ?",
                          (levels.norm_name(r["name"]), r["district"])).fetchall():
        if levels.merge_key(c["name"]) == mk and \
                levels.place_key(c["town"], c["chiefdom"]) == levels.place_key(r["town"]):
            return c
    return None


def ingest(conn, urls=None, out=None):
    t = db.now()
    out = out or config.DATA / "schoollist.jsonl"
    stats = {"files": 0, "rows": 0, "with_phone": 0, "matched": 0, "added": 0, "failed": 0}
    seen = set()
    with open(out, "w") as fh:
        for url in urls or URLS:
            path = config.CACHE / url.rsplit("/", 1)[-1]
            try:
                if not path.exists():
                    log(f"downloading {url}")
                    path.write_bytes(request(url, timeout=180))
                rows = parse(pdf_text(path))
            except Exception as e:
                stats["failed"] += 1
                log(f"  {url}: {e}")
                continue
            stats["files"] += 1
            log(f"  {path.name}: {len(rows)} rows")
            for r in rows:
                key = (r["emis"], levels.merge_key(r["name"]))
                if key in seen:  # the 2016 list repeats most 2017 schools; the newer row wins
                    continue
                seen.add(key)
                stats["rows"] += 1
                fh.write(json.dumps(record(r, url)) + "\n")
                row = _find(conn, r)
                if row:
                    conn.execute("UPDATE schools SET emis_code=COALESCE(emis_code, ?), levels=levels|?, "
                                 "town=COALESCE(town, ?), district=COALESCE(district, ?), province=COALESCE(province, ?), "
                                 "sources=?, updated_at=? WHERE id=?",
                                 (r["emis"], levels.BIT[r["level"]], r["town"], r["district"],
                                  levels.province(r["district"]), db.add_sources(row["sources"], url), t, row["id"]))
                    sid = row["id"]
                    stats["matched"] += 1
                else:
                    faith = levels.faith_from_name(r["name"])
                    sid = conn.execute(
                        "INSERT INTO schools(name, norm, kind, levels, ownership, denomination, district, province, "
                        "town, emis_code, sources, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r["name"], levels.norm_name(r["name"]), "school", levels.BIT[r["level"]],
                         r["owner"] or ("mission" if faith else "unknown"), faith, r["district"],
                         levels.province(r["district"]), r["town"], r["emis"], json.dumps([url]), t, t)).lastrowid
                    stats["added"] += 1
                if r["phone"]:
                    stats["with_phone"] += 1
                    db.upsert_contact(conn, sid, "phone", r["phone"], "research", source_url=url,
                                      confidence="medium", ts=t)
                    db.refresh_primary(conn, sid)
            conn.commit()
    stats["wrote"] = str(out)
    return stats
