"""Secondary-school principals and phone numbers from Teacher.co.ke's county lists.

Teacher.co.ke publishes, county by county, the 2020/21 list of public county
and sub-county secondary schools: sub-county, school, principal's name, school
phone number, school type (day/boarding, boys/girls/mixed) and enrolment.

Each list entry is one run of text ("Nairobi Dagoretti Beth Mugo High School
Emily Wanjiru Masele 0722291466 Day 863"), so it's read by finding which of the
county's known secondary schools appears in it; the words after the school's
name are the principal. Entries that match no known school, and whose school
name ends in a clear school word, are added as new schools (without map
coordinates).

The site deliberately breaks each email address into single-letter pieces to
stop address harvesters; those are not reassembled. Pages are fetched once,
cached, and read at one page every two seconds. robots.txt allows them.
"""

import hashlib
import html as htmllib
import json
import re
import time

from . import config, db, extract, levels, net
from .net import log

BASE = "https://teacher.co.ke/"
LIST_RE = re.compile(r"https://teacher\.co\.ke/[a-z-]+-county-list-of-all-(?:sub-)?county-secondary-schools-principals-and-school-contacts(?:-\d)?/$")
EXTRA_LISTS = ["https://teacher.co.ke/2020-list-of-all-county-secondary-schools-in-kenya-principal-and-contacts/"]
SCHOOL_WORD = re.compile(r"^(?:SCHOOL|SCH|SEC|SECONDARY|HIGH|ACADEMY|GIRLS|BOYS|MIXED|COMPLEX|COLLEGE|SS|HS)\.?,?$", re.I)
TYPE_RE = re.compile(r"\b(day|boarding|mixed|girls?|boys?)\b", re.I)


def _get(url):
    path = config.CACHE / "teacher" / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if not net.robots_allows(url):
        log(f"  robots.txt disallows {url}")
        return ""
    time.sleep(2)
    page = net.fetch_raw(url, timeout=30, max_bytes=4_000_000)
    if not page.ok:
        log(f"  {url}: {page.error or page.status}")
        return ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page.html, encoding="utf-8")
    return page.html


def list_urls():
    """Every county list page, from the site's sitemaps (cached)."""
    cache = config.CACHE / "teacher" / "list_urls.txt"
    if cache.exists():
        urls = [u.strip() for u in cache.read_text().splitlines() if LIST_RE.match(u.strip())]
        if urls:
            return urls + EXTRA_LISTS
    index = net.fetch_raw(BASE + "sitemap_index.xml").html
    urls = []
    for sm in re.findall(r"<loc>([^<]*post-sitemap\d*\.xml)</loc>", index):
        time.sleep(0.5)
        urls += [u for u in re.findall(r"<loc>([^<]*)</loc>", net.fetch_raw(sm).html) if LIST_RE.match(u)]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("\n".join(urls))
    return urls + EXTRA_LISTS


def entries(page_html):
    """(text before the emails, whole entry) for each list item."""
    for li in re.findall(r"<li>(.*?)</li>", page_html, re.S):
        if "<span>" not in li and not re.search(r"\d{9,}", re.sub(r"\D", "", li)):
            continue
        text = li.split("<span>", 1)[0]  # everything after is the split-up email: left alone
        text = htmllib.unescape(re.sub(r"<[^>]+>", " ", text))
        text = " ".join(text.split())
        if re.search(r"(?:\+?254|0)\s?[17]\d{2}\s?\d{3}\s?\d{3}", text):
            yield text


PHONE = re.compile(r"(?:\+?254|0)\s?(?:[17]\d{2}\s?\d{3}\s?\d{3}|[2-6]\d\s?\d{6,7})")


def parse(text):
    m = PHONE.search(text)
    if not m:
        return None
    before, after = text[:m.start()].strip(), text[m.end():].strip()
    enrol = None
    nums = re.findall(r"\b(\d{2,5})\b", after)
    if nums:
        n = int(nums[-1])
        enrol = n if 10 <= n <= 6000 else None
    kind = after.lower()
    gender = ("girls" if re.search(r"girl", kind) and not re.search(r"boy|mixed", kind) else
              "boys" if re.search(r"boy", kind) and not re.search(r"girl|mixed", kind) else
              "mixed" if re.search(r"mixed", kind) else None)
    boarding = ("day_boarding" if re.search(r"day", kind) and re.search(r"board", kind) else
                "boarding" if re.search(r"board", kind) else "day" if re.search(r"\bday\b", kind) else None)
    return {"before": before, "phone": extract.normalize_phone(m.group(0)), "students": enrol,
            "gender": gender, "boarding": boarding}


def match_tokens(name):
    """A school's identifying words, keeping Boys/Girls ("Makueni Boys" is not "Makueni Girls")."""
    return {t for t in levels.base_name(name).split() if len(t) > 1 and t not in ("ST", "ACADEMY")}


def undo(conn):
    """Remove everything a previous run of this step wrote, so it can run again cleanly."""
    conn.execute("DELETE FROM contacts WHERE source='list' AND source_url LIKE 'https://teacher.co.ke/%'")
    conn.execute("DELETE FROM schools WHERE sources='[\"teacher\"]' AND status='new'")
    rows = conn.execute("SELECT id, name, sources, extra FROM schools WHERE sources LIKE '%teacher%'").fetchall()
    for r in rows:
        extra = json.loads(r["extra"] or "{}")
        extra.pop("category", None)
        extra.pop("teacher_url", None)
        srcs = [x for x in json.loads(r["sources"]) if x != "teacher"]
        conn.execute("UPDATE schools SET students=NULL, gender=?, boarding=?, sources=?, extra=? WHERE id=?",
                     (levels.gender_from_name(r["name"]), levels.boarding_from_name(r["name"]), json.dumps(srcs),
                      json.dumps(extra), r["id"]))
        db.refresh_primary(conn, r["id"])
    conn.commit()
    return len(rows)


def place_names(conn, county, cache):
    """Sub-county, constituency, district and division names in a county, as word tuples."""
    if county not in cache:
        names = {r[0] for r in conn.execute("SELECT name FROM areas WHERE county_code=?", (county,))}
        for col in ("district", "division", "subcounty"):
            names |= {r[0] for r in conn.execute(f"SELECT DISTINCT {col} FROM schools WHERE county_code=? AND {col} IS NOT NULL", (county,))}
        cache[county] = sorted({tuple(re.sub(r"[^A-Z0-9 ]", " ", n.upper()).split()) for n in names if n},
                               key=len, reverse=True)
    return cache[county]


def find_start(upper, cw, places):
    """Index where the school's name begins: after the county and, when recognised, the sub-county
    (which may repeat the county's name: "Kajiado Central", "Kisii South")."""
    best = None
    for p in places:
        for at in (0, cw):
            if p and tuple(upper[at:at + len(p)]) == p and len(upper) - (at + len(p)) >= 2:
                end = at + len(p)
                if best is None or end > best:
                    best = end
    return (best, True) if best is not None and best >= cw else (cw, False)


def strip_subcounty(words, places):
    """Drop the sub-county the list puts before the school's name."""
    upper = [re.sub(r"[^A-Z0-9]", "", w.upper()) for w in words]
    for p in places:
        if p and tuple(upper[:len(p)]) == p and len(words) - len(p) >= 2:
            return words[len(p):]
    # unknown sub-county: assume one word, when that still leaves a real name
    return words[1:] if len(words) >= 3 else words


def _clean_principal(words):
    name = " ".join(words)
    name = re.sub(r",?\s*TSC\s*NO\.?.*$", "", name, flags=re.I)
    name = re.sub(r"^(?:MR|MRS|MS|MISS|DR|REV|SR|FR|MADAM)\.?\s+", "", name, flags=re.I)
    name = name.strip(" ,.-")
    parts = name.split()
    if not 2 <= len(parts) <= 5 or re.search(r"\d|@", name):
        return None
    return " ".join(p.capitalize() if p.isupper() or p.islower() else p for p in parts)


def ingest(conn):
    if conn.execute("SELECT 1 FROM contacts WHERE source='list' AND source_url LIKE 'https://teacher.co.ke/%' LIMIT 1").fetchone():
        undo(conn)
    urls = list_urls()
    log(f"  reading {len(urls)} county lists from teacher.co.ke")
    counties = {r["name"].lower().replace("-", " ").replace("'", ""): r["code"]
                for r in conn.execute("SELECT code, name FROM areas WHERE kind='county'")}
    counties.update({"muranga": counties.get("murang a") or counties.get("muranga"), "tharaka nithi": counties.get("tharaka nithi")})
    by_county = {}
    for r in conn.execute("SELECT id, name, county_code FROM schools WHERE levels & 8"):
        by_county.setdefault(r["county_code"], []).append((r["id"], match_tokens(r["name"]), r["name"]))
    stats = {"entries": 0, "matched": 0, "new": 0, "unplaced": 0, "phones": 0, "principals": 0}
    exact, place_cache = {}, {}
    ts = db.now()
    seen_rows = set()
    for url in urls:
        page = _get(url)
        if not page:
            continue
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        category = "Sub-County" if "sub-county" in slug else "County"
        m = re.match(r"([a-z-]+?)-county-list", slug)
        page_county = counties.get(m.group(1).replace("-", " ")) if m else None
        for text in entries(page):
            rec = parse(text)
            if not rec or not rec["phone"]:
                continue
            key = (rec["phone"], rec["before"][:40])
            if key in seen_rows:
                continue
            seen_rows.add(key)
            stats["entries"] += 1
            words = rec["before"].split()
            county = page_county
            if county is None:  # the national list names the county first
                for k in (3, 2, 1):
                    c = counties.get(" ".join(words[:k]).lower().replace("-", " ").replace("'", ""))
                    if c:
                        county = c
                        break
            if county is None:
                stats["unplaced"] += 1
                continue
            upper = [re.sub(r"[^A-Z0-9]", "", w.upper()) for w in words]
            cname = conn.execute("SELECT name FROM areas WHERE code=?", (county,)).fetchone()["name"]
            cw = len(cname.replace("-", " ").split())
            if " ".join(upper[:cw]) != re.sub(r"[^A-Z0-9 ]", "", cname.upper().replace("-", " ")):
                cw = 0
            # the entry text ends at the first number (enrolment or a stray code sits after the name)
            nd = next((i for i, w in enumerate(words) if re.search(r"\d", w)), len(words))
            words, upper = words[:nd], upper[:nd]
            start, known_place = find_start(upper, cw, place_names(conn, county, place_cache))
            span = upper[start:]
            best = None
            for sid, toks, name in by_county.get(county, ()):
                if not toks:
                    continue
                if known_place and toks <= set(span):
                    pos = [start + i for i, w in enumerate(span) if w in toks]
                elif toks <= set(span[1:]):  # unknown sub-county: its first word isn't the school's
                    pos = [start + 1 + i for i, w in enumerate(span[1:]) if w in toks]
                else:
                    continue
                if len(toks) == 1:
                    # one word ("Kiambu", "Central") identifies a school only when a school word follows it
                    i = pos[0]
                    if len(next(iter(toks))) < 5 or i + 1 >= len(words) or not SCHOOL_WORD.match(words[i + 1]):
                        continue
                score = (len(toks), sum(len(t) for t in toks), -max(pos))
                if best is None or score > best[0]:
                    best = (score, sid, max(pos), toks)
            cut = max((i for i, w in enumerate(words) if SCHOOL_WORD.match(w) and i >= start), default=None)
            if not best and cut is not None:
                # an earlier entry already added this school: same name exactly
                hit = exact.get(county, {}).get(frozenset(match_tokens(" ".join(words[start + (0 if known_place else 1):cut + 1]))))
                if hit:
                    best = ((0, 0, 0), hit, cut, None)
            principal = None
            if best:
                sid, last = best[1], best[2]
                tail = words[last + 1:]
                while tail and SCHOOL_WORD.match(tail[0]):
                    tail = tail[1:]
                principal = _clean_principal(tail)
                stats["matched"] += 1
            else:
                # a school the directory doesn't have yet: its name ends at the last school word
                if cut is None:
                    continue
                school_words = words[start + (0 if known_place or cut - start < 2 else 1):cut + 1]
                while len(school_words) > 2 and re.fullmatch(r"(?i)north|south|east|west|central|homabay", school_words[0]):
                    school_words = school_words[1:]  # the tail of a sub-county name ("Nakuru West")
                if len(school_words) < 2:
                    continue
                name = levels.display_name(" ".join(school_words))
                principal = _clean_principal(words[cut + 1:])
                area = conn.execute("SELECT name FROM areas WHERE code=?", (county,)).fetchone()
                cur = conn.execute(
                    """INSERT INTO schools(name, levels, ownership, county_code, county, gender, boarding, students,
                         sources, extra, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (name, levels.SENIOR, "public", county, area["name"] if area else None, rec["gender"],
                     rec["boarding"], rec["students"], json.dumps(["teacher"]),
                     json.dumps({"category": category, "teacher_url": url}), ts, ts))
                sid = cur.lastrowid
                exact.setdefault(county, {})[frozenset(match_tokens(name))] = sid
                stats["new"] += 1
            row = conn.execute("SELECT gender, boarding, students, sources, extra FROM schools WHERE id=?", (sid,)).fetchone()
            extra = json.loads(row["extra"] or "{}")
            extra.update({"category": category, "teacher_url": url})
            fields = {"sources": db.add_sources(row["sources"], "teacher"), "extra": json.dumps(extra)}
            for col in ("gender", "boarding"):
                if not row[col] and rec[col]:
                    fields[col] = rec[col]
            if rec["students"]:
                fields["students"] = rec["students"]  # 2020 enrolment is newer than anything else on file
            conn.execute(f"UPDATE schools SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), sid))
            db.upsert_contact(conn, sid, "phone", rec["phone"], "list", source_url=url, score=3, ts=ts)
            stats["phones"] += 1
            if principal:
                db.upsert_contact(conn, sid, "person", principal, "list", label="Principal", source_url=url,
                                  score=8, ts=ts)
                stats["principals"] += 1
            db.refresh_primary(conn, sid)
        conn.commit()
    levels.apply_all_grades(conn)
    conn.commit()
    return stats
