"""TVET colleges' emails and phones from the TVET Authority's register of licensed institutions.

The TVET Authority (TVETA) publishes its register of licensed institutions as a
PDF: name, postal address, phone, email, category, public/private, county. The
text is read from data/cache/tveta_register.txt (extract it from the PDF once,
e.g. with pypdf). Each institution is matched to a directory TVET school in
the same county by name, or added as a new post-secondary school.
"""

import json
import re

from . import config, db, extract, levels, osm
from .net import log

SOURCE_URL = "https://ajirayako.co.tz/wp-content/uploads/2023/01/Licensed-TVET-institutions-in-Kenya-2.pdf"
GENERIC = {"VOCATIONAL", "TRAINING", "CENTRE", "CENTER", "INSTITUTE", "COLLEGE", "POLYTECHNIC", "TECHNICAL",
           "YOUTH", "MANAGEMENT", "KENYA", "OF", "AND", "THE", "VTC", "TTI", "TVC", "CAMPUS", "STUDIES",
           "PROFESSIONAL", "TECHNOLOGY", "SCIENCE", "SCIENCES", "BUSINESS", "HEALTH", "MEDICAL", "COMPUTER",
           "INTERNATIONAL", "SCHOOL", "ACADEMY", "INFORMATION", "DEVELOPMENT", "HOSPITALITY", "BEAUTY", "HAIR"}


def distinct(tokens):
    return {t for t in tokens if t not in GENERIC}


EMAIL = re.compile(r"[a-z0-9][a-z0-9._%+'-]{0,63}@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,6}(?![a-z])")


def records(text):
    cur = None
    for line in text.splitlines():
        if re.match(r"^\d{1,4} [A-Z0-9]", line):
            if cur:
                yield cur
            cur = [line]
        elif cur is not None:
            cur.append(line)
    if cur:
        yield cur


def parse(lines, county_names):
    first = re.sub(r"^\d+ ", "", lines[0])
    name_parts = [first]
    for l in lines[1:]:
        if re.match(r"^(P\.?\s?O|BOX|\d)", l.strip(), re.I):
            break
        name_parts.append(l)
    name = " ".join(" ".join(name_parts).split())
    blob = "\n".join(lines)
    joined = re.sub(r"\n(?=[a-z0-9@.\-_]*[@.])|(?<=[@.\-_])\n", "", blob)  # re-join emails wrapped across lines
    emails = []
    for e in EMAIL.findall(joined):
        e = re.sub(r"^[\d-]{5,}", "", e)  # a phone number the PDF ran into the address
        e = extract.clean_email(e)
        if e and e not in emails:
            emails.append(e)
    phones = []
    for m in re.finditer(r"(?<!\d)(?:0|254)?\s?[17]\d{2}[\s-]?\d{3}[\s-]?\d{3}(?!\d)", blob):
        p = extract.normalize_phone(m.group(0) if m.group(0).startswith(("0", "254")) else "0" + m.group(0))
        if p and p not in phones:
            phones.append(p)
    county = None
    up = blob.upper()
    for cname, code in county_names:
        if re.search(rf"\b{re.escape(cname)}\b", up):
            county = code
    ownership = "private" if "PRIVATE" in up else "public" if "PUBLIC" in up else None
    return name, emails[:2], phones[:2], county, ownership


def undo(conn):
    conn.execute("DELETE FROM contacts WHERE source_url=?", (SOURCE_URL,))
    conn.execute("DELETE FROM schools WHERE sources='[\"tveta\"]' AND status='new'")
    for r in conn.execute("SELECT id FROM schools WHERE sources LIKE '%tveta%'").fetchall():
        db.refresh_primary(conn, r["id"])
    conn.commit()


def ingest(conn):
    undo(conn)
    path = config.CACHE / "tveta_register.txt"
    if not path.exists():
        raise SystemExit(f"Extract the TVETA register PDF's text to {path} first.")
    cn = [(r["name"].upper().replace("-", " "), r["code"]) for r in conn.execute("SELECT code, name FROM areas WHERE kind='county'")]
    cn += [(n.replace(" ", "-"), c) for n, c in cn if " " in n] + [("MURANGA", c) for n, c in cn if n.startswith("MURANG")]
    cands = {}
    for r in conn.execute("SELECT id, name, county_code FROM schools WHERE levels & (16|32|64|128)"):
        cands.setdefault(r["county_code"], []).append((r["id"], levels.tokens(r["name"])))
    stats = {"records": 0, "matched": 0, "new": 0, "emails": 0}
    ts = db.now()
    for rec in records(path.read_text()):
        name, emails, phones, county, own = parse(rec, cn)
        if not emails and not phones:
            continue
        stats["records"] += 1
        toks = levels.tokens(name)
        places = {n for n, _ in cn} | {w for n, _ in cn for w in n.split()}
        if not distinct(toks) - places:
            continue  # "Vocational Training Centre": the register's name was cut off; can't tell which one
        best = None
        for sid, t in cands.get(county, ()):
            if not (distinct(toks) & distinct(t)) - places:
                continue
            s = osm.name_score(toks, t)
            if s >= 0.75 and (best is None or s > best[0]):
                best = (s, sid)
        if best:
            sid = best[1]
            stats["matched"] += 1
        elif county and toks:
            area = conn.execute("SELECT name FROM areas WHERE code=?", (county,)).fetchone()
            sid = conn.execute("""INSERT INTO schools(name, levels, ownership, county_code, county, sources, extra,
                                    created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                               (levels.display_name(name), levels.TVET, own, county, area["name"], json.dumps(["tveta"]),
                                json.dumps({"category": "TVET (licensed by TVETA)"}), ts, ts)).lastrowid
            cands.setdefault(county, []).append((sid, toks))
            stats["new"] += 1
        else:
            continue
        for e in emails:
            db.upsert_contact(conn, sid, "email", e, "list", label=extract.email_role(e), source_url=SOURCE_URL, score=4, ts=ts)
            stats["emails"] += 1
        for p in phones:
            db.upsert_contact(conn, sid, "phone", p, "list", source_url=SOURCE_URL, score=3, ts=ts)
        cur = conn.execute("SELECT sources FROM schools WHERE id=?", (sid,)).fetchone()
        conn.execute("UPDATE schools SET sources=? WHERE id=?", (db.add_sources(cur["sources"], "tveta"), sid))
        db.refresh_primary(conn, sid)
    levels.apply_all_grades(conn)
    conn.commit()
    return stats
