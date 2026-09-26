"""Private-school emails, phones and addresses from Enhanced Education Group's directories.

eeducationgroup.com publishes contact lists of Kenya's private primary and
secondary schools, international schools, kindergartens, Montessori schools,
private TVETs and universities. Each entry gives the school's name, email,
telephone, postal address and physical location, in plain text. There's no
county, so a school is placed by its postal town (and failing that its
physical location), and matched to a directory school by name within that
county. Schools the directory doesn't have are added, in the county of their
postal town, without map coordinates.

Pages are fetched once, cached in data/cache/eeg/, at one every two seconds;
robots.txt allows them.
"""

import hashlib
import html as htmllib
import json
import re
import time

from . import config, db, extract, levels, net, osm
from .net import log

PAGES = {
    "private-primary-schools-in-kenya-contacts": levels.ECDE | levels.PRIMARY,
    "private-primary-schools-in-kenya": levels.ECDE | levels.PRIMARY,
    "private-secondary-schools-in-kenya-contacts": levels.SENIOR,
    "local-private-secondary-schools-in-kenya": levels.SENIOR,
    "international-primary-schools-in-kenya-contacts": levels.ECDE | levels.PRIMARY,
    "international-secondary-schools-in-kenya-contacts": levels.SENIOR,
    "kindergarten-in-kenya-contacts": levels.ECDE,
    "montessori-schools-in-kenya": levels.ECDE,
    "private-schools-directory": 0,
    "private-technical-and-vocational-education-and-training-tvets-in-kenya": levels.TVET,
    "private-universities-in-kenya-contacts": levels.UNIVERSITY,
    "local-private-universities-in-kenya": levels.UNIVERSITY,
    "local-public-universities-in-kenya": levels.UNIVERSITY,
}
BASE = "https://www.eeducationgroup.com/"


def _get(url):
    path = config.CACHE / "eeg" / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if not net.robots_allows(url):
        log(f"  robots.txt disallows {url}")
        return ""
    time.sleep(2)
    page = net.fetch_raw(url, timeout=40, max_bytes=6_000_000)
    if not page.ok:
        log(f"  {url}: {page.error or page.status}")
        return ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page.html, encoding="utf-8")
    return page.html


FIELD = re.compile(r"^(Categories|Email|E-mail|Telephone|Tel|Mobile|Cell|Postal Address|Physical Location|Location|Website)\s*:?\s*(.*)$", re.I)


def entries(page_html):
    body = page_html[page_html.find("entry-content"):] if "entry-content" in page_html else page_html
    for block in re.findall(r"<p[^>]*>(.*?)</p>", body, re.S):
        lines = [htmllib.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.split(r"<br\s*/?>", block)]
        lines = [" ".join(x.split()) for x in lines if x.strip()]
        if len(lines) < 2 or not any(FIELD.match(x) for x in lines[1:]):
            continue
        rec = {"name": lines[0], "emails": [], "phones": [], "postal": None, "location": None, "website": None}
        for line in lines[1:]:
            m = FIELD.match(line)
            if not m:
                continue
            key, val = m.group(1).lower(), m.group(2)
            if key in ("email", "e-mail"):
                rec["emails"] += [e for e in (extract.clean_email(x) for x in re.split(r"[,;/\s]+|\band\b", val)) if e]
            elif key in ("telephone", "tel", "mobile", "cell"):
                rec["phones"] += [p for p in (extract.normalize_phone(x) for x in re.split(r"[,;/]|\band\b", val)) if p]
            elif key == "postal address":
                rec["postal"] = val
            elif key in ("physical location", "location"):
                rec["location"] = val
            elif key == "website":
                rec["website"] = val
        if rec["name"] and len(rec["name"]) < 120 and (rec["emails"] or rec["phones"]):
            yield rec


def _postal(val):
    """'P.O. Box 552, Nairobi 00606' -> ('P.O. Box 552-00606, Nairobi', 'Nairobi')."""
    m = re.search(r"Box\s*(\d{1,6})\s*[-,]?\s*(\d{5})?\s*,?\s*([A-Za-z][A-Za-z' .-]+?)\s*[-,]?\s*(\d{5})?\s*$", val or "", re.I)
    if not m:
        return None, None
    town = m.group(3).strip(" .-").title()
    return extract.format_pobox(m.group(1), m.group(2) or m.group(4), town), town


def _clean_name(name):
    name = re.sub(r"[’']\s*The$", "", name).strip()
    m = re.match(r"^(.*?),?\s+The$", name)
    if m:
        name = "The " + m.group(1)
    return levels.display_name(name)


class Places:
    """Town / area name -> county code, from boundaries and the Ministry list's place names."""

    def __init__(self, conn):
        votes = {}
        for r in conn.execute("SELECT name, code, county_code, kind FROM areas"):
            votes.setdefault(r["name"].upper(), {})[r["code"] if r["kind"] == "county" else r["county_code"]] = 1000
        for col in ("town", "district", "division", "location", "sublocation", "subcounty"):
            for r in conn.execute(f"SELECT UPPER({col}) AS v, county_code, COUNT(*) AS n FROM schools "
                                  f"WHERE {col} IS NOT NULL AND county_code IS NOT NULL GROUP BY 1, 2"):
                d = votes.setdefault(r["v"], {})
                d[r["county_code"]] = d.get(r["county_code"], 0) + r["n"]
        self.best = {}
        for name, d in votes.items():
            code, n = max(d.items(), key=lambda kv: kv[1])
            if n >= 3 and n >= 0.7 * sum(d.values()):
                self.best[name] = code

    def county(self, *texts):
        for text in texts:
            if not text:
                continue
            words = re.sub(r"[^A-Za-z' -]", " ", text).upper().split()
            for size in (3, 2, 1):
                for i in range(len(words) - size + 1):
                    code = self.best.get(" ".join(words[i:i + size]))
                    if code:
                        return code
        return None


def ingest(conn):
    places = Places(conn)
    index = {}
    rows = {}
    for r in conn.execute("SELECT id, name, county_code, levels FROM schools"):
        toks = levels.tokens(r["name"])
        rows[r["id"]] = (toks, r["county_code"], r["levels"])
        for t in toks:
            index.setdefault(t, set()).add(r["id"])
    stats = {"entries": 0, "matched": 0, "new": 0, "no_county": 0, "emails": 0, "phones": 0}
    ts = db.now()
    seen = set()
    for slug, page_mask in PAGES.items():
        url = BASE + slug + "/"
        page = _get(url)
        for rec in entries(page):
            key = (rec["name"].lower(), tuple(rec["emails"]), tuple(rec["phones"]))
            if key in seen:
                continue
            seen.add(key)
            stats["entries"] += 1
            name = _clean_name(rec["name"])
            addr, town = _postal(rec["postal"])
            county = places.county(town, rec["location"])
            mask = levels.levels_from_name(name) or page_mask
            toks = levels.tokens(name)
            cands = set()
            for t in toks:
                cands |= index.get(t, set())
            best = None
            for sid in cands:
                stoks, scounty, slevels = rows[sid]
                if county and scounty and scounty != county:
                    continue
                if mask and slevels and not (mask & slevels):
                    continue
                sc = osm.name_score(toks, stoks)
                need = 0.75 if county and scounty == county else 0.95
                if sc >= need and (best is None or sc > best[0]):
                    best = (sc, sid)
            if best:
                sid = best[1]
                stats["matched"] += 1
            else:
                if not county or not toks:
                    stats["no_county"] += 1
                    continue
                area = conn.execute("SELECT name FROM areas WHERE code=?", (county,)).fetchone()
                cur = conn.execute(
                    """INSERT INTO schools(name, levels, ownership, county_code, county, town, sources, extra,
                         created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (name, mask, "private" if "public" not in slug else "public", county, area["name"], town,
                     json.dumps(["eeg"]), json.dumps({"physical_location": rec["location"]}), ts, ts))
                sid = cur.lastrowid
                rows[sid] = (toks, county, mask)
                for t in toks:
                    index.setdefault(t, set()).add(sid)
                stats["new"] += 1
            for e in rec["emails"]:
                db.upsert_contact(conn, sid, "email", e, "list", label=extract.email_role(e), source_url=url, score=4, ts=ts)
                stats["emails"] += 1
            for p in rec["phones"][:3]:
                db.upsert_contact(conn, sid, "phone", p, "list", source_url=url, score=3, ts=ts)
                stats["phones"] += 1
            if addr:
                db.upsert_contact(conn, sid, "address", addr, "list", source_url=url, score=2, ts=ts)
            if rec["website"]:
                for kind, value, label in osm.url_contacts(rec["website"]):
                    db.upsert_contact(conn, sid, kind, value, "list", source_url=url, score=2, ts=ts)
            cur = conn.execute("SELECT sources, extra FROM schools WHERE id=?", (sid,)).fetchone()
            extra = json.loads(cur["extra"] or "{}")
            if rec["location"]:
                extra.setdefault("physical_location", rec["location"])
            conn.execute("UPDATE schools SET sources=?, extra=? WHERE id=?",
                         (db.add_sources(cur["sources"], "eeg"), json.dumps(extra), sid))
            db.refresh_primary(conn, sid)
        conn.commit()
    levels.apply_all_grades(conn)
    conn.commit()
    return stats
