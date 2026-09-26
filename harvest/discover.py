"""Find websites for schools that don't have one on file.

Kenyan schools register their sites under two dedicated domains: .sc.ke (for
schools) and .ac.ke (for academic institutions, and many secondary schools).
For each school this step builds the handful of addresses its name suggests
(alliancegirls.sc.ke, alliancegirlshigh.ac.ke, ...), keeps those that exist,
and accepts one only when the page itself names the school. Nothing is
guessed into the record: an address is added only when the site's title or
opening text carries every distinctive word of the school's name.

With BRAVE_API_KEY set, schools still without a site are also looked up with
the Brave Search API (free tier: 2,000 queries a month), and a result is
accepted under the same test.
"""

import re
import socket
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, db, extract, levels, net
from .net import log

TLDS = ("sc.ke", "ac.ke", "co.ke", "or.ke")
# Directory, news and social sites that list schools but aren't the school's own site.
NOT_OWN_SITE = re.compile(
    r"facebook|instagram|twitter|x\.com|youtube|tiktok|linkedin|wikipedia|wikidata|google\.|maps\.|"
    r"kenyaplex|schoolsnet|advance-africa|elimu|kenyans\.co\.ke|nation\.africa|standardmedia|the-star|tuko|"
    r"schoolandcollegelistings|findaschool|shuleyangu|kenyaschools|schools\.co\.ke|softkenya|knec|"
    r"education\.go\.ke|nemis|zoominfo|yelp|cybo|infoisinfo|businesslist|yellowpages|kenyayote|africabizinfo|"
    r"mapcarta|waze|foursquare|glassdoor|indeed|brightermonday|myjobmag|educationnewshub|teacher\.co\.ke|"
    r"kenyadmission|schoolsportal|kcse|kcpe|newsblaze|ghafla|pulselive|kenyaschoolsguide|schoolmart",
    re.I)

_dns_cache = {}
_dns_lock = threading.Lock()


def _resolves(host):
    with _dns_lock:
        if host in _dns_cache:
            return _dns_cache[host]
    try:
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        ok = True
    except (socket.gaierror, UnicodeError, OSError):
        ok = False
    with _dns_lock:
        _dns_cache[host] = ok
    return ok


def slugs(name, mask):
    """Candidate host labels for a school's own domain."""
    base = levels.base_name(name).lower().split()
    core = [t for t in base if t not in ("st",)]
    if not core:
        return []
    joined = "".join(core)
    if len(joined) < 4:
        return []
    out = [joined]
    words = name.lower()
    if mask & levels.SENIOR:
        out += [joined + "high", joined + "highschool", joined + "school", joined + "sec", joined + "secondary",
                joined + "hs"]
    if mask & (levels.PRIMARY | levels.ECDE):
        out += [joined + "school", joined + "schools", joined + "primary", joined + "academy"]
    if "academy" in words:
        out += [joined + "academy"]
    if mask & (levels.TVET | levels.TTC | levels.UNIVERSITY):
        out += [joined + "college", joined + "tvc", joined + "ttc", joined + "poly", joined + "university",
                joined + "institute"]
    if len(core) > 1:
        out.append("-".join(core))
        out.append("".join(w[0] for w in core) + ("hs" if mask & levels.SENIOR else ""))
    seen, uniq = set(), []
    for s in out:
        s = re.sub(r"[^a-z0-9-]", "", s)
        if 3 <= len(s) <= 40 and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq[:10]


def page_names_school(page, name):
    """Does this page say it's this school? All distinctive name words must
    appear in the title, description or opening text."""
    data = extract.extract(page.html, page.final_url)
    if data["parked"]:
        return False
    hay = " ".join((data["title"], data["description"], data["visible_text"][:2500])).upper()
    hay = re.sub(r"[^A-Z0-9 ]+", " ", hay.replace("'", ""))
    toks = levels.tokens(name) or set(levels.base_name(name).split())
    if not toks:
        return False
    if not all(re.search(rf"\b{re.escape(t)}\b", hay) for t in toks):
        return False
    return bool(re.search(r"\bSCHOOL|\bACADEMY|\bCOLLEGE|\bUNIVERSITY|\bINSTITUTE|\bPOLYTECHNIC|\bHIGH\b|"
                          r"\bSECONDARY|\bPRIMARY|\bKINDERGARTEN|\bLEARNERS|\bPUPILS|\bSTUDENTS", hay))


def guess_site(name, mask, private=False):
    # .sc.ke and .ac.ke are where schools register; commercial suffixes only for private and tertiary schools
    tlds = TLDS if private or mask & (levels.TVET | levels.TTC | levels.UNIVERSITY) else TLDS[:2]
    for slug in slugs(name, mask)[:8]:
        for tld in tlds:
            for host in (f"{slug}.{tld}", f"www.{slug}.{tld}"):
                if not _resolves(host):
                    continue
                if not net.robots_allows(f"https://{host}/"):
                    return None
                page = net.fetch_raw(f"https://{host}/", timeout=10)
                if not page.ok:
                    page = net.fetch_raw(f"http://{host}/", timeout=10)
                if page.ok and page_names_school(page, name):
                    return page.final_url.rstrip("/")
                break  # the bare host answered for this slug; no need to try www.
    return None


_brave_lock = threading.Lock()
_brave_last = [0.0]


def brave_site(name, county):
    if not config.BRAVE_API_KEY:
        return None
    with _brave_lock:  # free tier: 1 query per second
        wait = 1.05 - (time.time() - _brave_last[0])
        if wait > 0:
            time.sleep(wait)
        _brave_last[0] = time.time()
    q = f'"{name}" {county or ""} Kenya school'
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode({"q": q, "count": 8,
                                                                                      "country": "KE"})
    try:
        data = net.request_json(url, headers={"X-Subscription-Token": config.BRAVE_API_KEY,
                                              "Accept": "application/json"}, timeout=20, retries=2)
    except Exception as e:
        log(f"  Brave search failed: {str(e)[:100]}")
        return None
    for r in (data.get("web") or {}).get("results", []):
        u = r.get("url") or ""
        host = urllib.parse.urlsplit(u).netloc.lower()
        if not host or NOT_OWN_SITE.search(host):
            continue
        root = f"{urllib.parse.urlsplit(u).scheme}://{host}/"
        if not net.robots_allows(root):
            continue
        page = net.fetch_raw(root, timeout=10)
        if page.ok and page_names_school(page, name):
            return page.final_url.rstrip("/")
    return None


DEFAULT_WHERE = ("(s.levels & (8|16|32|64) OR s.ownership='private' OR s.levels & 4)")


def select(conn, counties=None, limit=None, level_keys=None, stale_days=None):
    where = ["s.website IS NULL", "s.lat IS NOT NULL"]
    params = []
    if level_keys:
        mask = 0
        for k in level_keys.split(","):
            if k.strip() not in levels.BY_KEY:
                raise SystemExit(f"Unknown level {k}; use {', '.join(levels.BY_KEY)}")
            mask |= levels.BY_KEY[k.strip()]
        where.append(f"s.levels & {mask}")
    else:
        where.append(DEFAULT_WHERE)
    if stale_days is None:
        where.append("s.discovered_at IS NULL")
    else:
        where.append("(s.discovered_at IS NULL OR s.discovered_at < ?)")
        params.append(db.now() - stale_days * 86400)
    if counties:
        where.append(f"s.county_code IN ({','.join('?' * len(counties))})")
        params += counties
    q = (f"SELECT s.id, s.name, s.levels, s.county, s.ownership FROM schools s WHERE {' AND '.join(where)} "
         f"ORDER BY (s.levels & 8) DESC, (s.levels & 64) DESC, s.ownership='private' DESC, s.id")
    if limit:
        q += f" LIMIT {int(limit)}"
    return conn.execute(q, params).fetchall()


def _one(row):
    site = guess_site(row["name"], row["levels"], row["ownership"] == "private")
    how = "guessed .ke domain"
    if not site:
        site = brave_site(row["name"], row["county"])
        how = "Brave Search"
    return row["id"], site, how


def run(conn, counties=None, limit=None, levels=None, stale_days=None, workers=16):
    rows = select(conn, counties, limit, levels, stale_days)
    total = len(rows)
    if not total:
        log("  nothing to look up")
        return {"checked": 0, "found": 0}
    log(f"  looking for websites of {total:,} schools"
        + (" (domain checks + Brave Search)" if config.BRAVE_API_KEY else " (domain checks; set BRAVE_API_KEY to add web search)"))
    found = done = 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=max(4, workers)) as pool:
        futs = [pool.submit(_one, r) for r in rows]
        for fut in as_completed(futs):
            try:
                sid, site, how = fut.result()
            except Exception:
                continue
            ts = db.now()
            conn.execute("UPDATE schools SET discovered_at=? WHERE id=?", (ts, sid))
            if site:
                db.upsert_contact(conn, sid, "website", site, "search", label=f"found by {how}", source_url=site,
                                  score=1, ts=ts)
                cur = conn.execute("SELECT sources FROM schools WHERE id=?", (sid,)).fetchone()
                conn.execute("UPDATE schools SET sources=?, enrich_status=NULL WHERE id=?",
                             (db.add_sources(cur["sources"], "web"), sid))
                db.refresh_primary(conn, sid)
                found += 1
            conn.commit()  # commit each school so the CRM can write while this runs
            done += 1
            if done % 50 == 0 or done == total:
                rate = done / max(time.time() - started, 1)
                log(f"  {done:,}/{total:,} checked, {found:,} websites found  ~{(total - done) / rate / 60:.0f} min left")
    conn.commit()
    dropped = drop_shared(conn)
    return {"checked": total, "found": found - dropped, "dropped_shared": dropped}


def drop_shared(conn):
    """A guessed site that two different schools both "found" belongs to at most
    one of them, and the name test can't say which: retire it from all of them."""
    rows = conn.execute("""SELECT value FROM contacts WHERE kind='website' AND source='search' AND active=1
                           GROUP BY value HAVING COUNT(DISTINCT school_id) > 1""").fetchall()
    n = 0
    for r in rows:
        ids = [x[0] for x in conn.execute("SELECT school_id FROM contacts WHERE kind='website' AND source='search' "
                                          "AND value=?", (r["value"],))]
        conn.execute("UPDATE contacts SET active=0, label='shared by several schools' WHERE kind='website' "
                     "AND source='search' AND value=?", (r["value"],))
        for sid in ids:
            db.refresh_primary(conn, sid)
        n += len(ids)
    conn.commit()
    if n:
        log(f"  retired {len(rows)} guessed sites that matched more than one school")
    return n
