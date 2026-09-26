"""Visit each school's website and record what it says today.

For every school with a website: fetch the home page, then up to four contact /
principal / about / admissions pages, and extract emails, phone numbers,
P.O. Box addresses, social profiles and named leaders (principal, head teacher,
director, BOM chair). Every value is stored with the page it came from and when
it was last seen; values that disappear from the site are retired, not deleted.
Re-running with --stale-days re-verifies anything older than that.

Politeness: robots.txt is honoured, at most two requests run against one site
at a time, the crawler names itself in its user agent, and a site that answers
401/403/429 is recorded as blocked and left alone.
"""

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlsplit

from . import db, extract, net
from .net import log

MAX_SUBPAGES = 4
LOGIN_HOSTS = {"accounts.google.com", "login.microsoftonline.com", "facebook.com", "m.facebook.com",
               "login.live.com"}
GUESSES = ("/contact", "/contact-us", "/contacts", "/contact-us/", "/about-us", "/admissions")
SOCIAL_HOSTS = ("facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com", "tiktok.com",
                "linkedin.com")

_host_locks = {}
_host_locks_guard = threading.Lock()


def _host_slot(url):
    key = extract.registrable(_host(url))
    with _host_locks_guard:
        if key not in _host_locks:
            _host_locks[key] = threading.BoundedSemaphore(2)
        return _host_locks[key]


def _host(url):
    h = urlsplit(url).netloc.lower().split(":")[0]
    return h[4:] if h.startswith("www.") else h


def _same_site(a, b):
    return extract.registrable(_host(a)) == extract.registrable(_host(b))


def _fetch_home(url):
    page = net.fetch_raw(url)
    if page.ok:
        return page
    alt = ("https://" + url[7:]) if url.startswith("http://") else ("http://" + url[8:]) if url.startswith("https://") else None
    if alt and page.error not in ("dns", "not a public address") and page.status not in (401, 403, 429):
        page2 = net.fetch_raw(alt)
        if page2.ok:
            return page2
    return page


def crawl_site(url):
    """Network-only work; safe to run in a thread. Returns a plain dict."""
    if any(_host(url).endswith(h) for h in SOCIAL_HOSTS):
        return {"url": url, "status": "social", "error": "a social profile, not a website"}
    with _host_slot(url):
        return _crawl_site(url)


def _crawl_site(url):
    started = time.time()
    res = {"url": url, "status": "error", "error": None, "final_url": None, "pages": [],
           "emails": {}, "phones": {}, "socials": {}, "social_pages": {}, "people": {}, "addresses": {},
           "contact_pages": [], "contact_forms": [], "title": "", "description": "", "students": None,
           "closed_hint": False}
    if not net.robots_allows(url):
        res.update(status="robots", error="robots.txt disallows crawling")
        return res
    home = _fetch_home(url)
    if not home.ok:
        if home.error in ("dns", "refused") or (home.status in (404, 410) and not home.html):
            res.update(status="dead", error=home.error or f"HTTP {home.status}")
        elif home.status in (401, 403, 429, 503):
            res.update(status="blocked", error=f"HTTP {home.status}")
        else:
            res.update(status="error", error=home.error or f"HTTP {home.status}")
        return res
    if "html" not in home.content_type and "text" not in home.content_type and home.content_type:
        res.update(status="error", error=f"not a web page ({home.content_type[:40]})")
        return res
    if _host(home.final_url) in LOGIN_HOSTS:
        res.update(status="blocked", error="site requires sign-in")
        return res
    res["final_url"] = home.final_url
    first = extract.extract(home.html, home.final_url)
    if first["parked"]:
        res.update(status="parked", error="domain parked, expired or for sale", title=first["title"])
        return res
    res.update(title=first["title"], description=first["description"])
    _absorb(res, first, home.final_url, is_contact=False)

    # Follow-up pages: contact first, then the principal's page, then about/admissions.
    contact, leader, about = [], [], []
    seen = {home.final_url.rstrip("/")}
    for href, text in first["links"]:
        if not href.startswith(("http://", "https://")) or not _same_site(href, home.final_url):
            continue
        clean = href.split("#")[0].rstrip("/")
        if clean in seen or re.search(r"\.(pdf|jpe?g|png|gif|docx?|xlsx?|mp3|mp4|zip)$", clean, re.I):
            continue
        label = f"{urlsplit(clean).path.lower()} {text}"
        if extract.CONTACT_LINK.search(label):
            contact.append(clean)
        elif re.search(r"principal|head[-_ ]?teacher|message|administration|management|leadership|staff", label, re.I):
            leader.append(clean)
        elif extract.ABOUT_LINK.search(label):
            about.append(clean)
        seen.add(clean)
    queue = (contact[:1] + leader[:2] + about[:1] + contact[1:2])[:MAX_SUBPAGES]
    if not contact:
        queue = ([urljoin(home.final_url, g) for g in GUESSES[:3]] + queue)[:MAX_SUBPAGES + 2]
    for sub in queue:
        if not net.robots_allows(sub):
            continue
        page = net.fetch_raw(sub, timeout=10)
        if not page.ok or not _same_site(page.final_url, home.final_url):
            continue
        data = extract.extract(page.html, page.final_url)
        _absorb(res, data, page.final_url, is_contact=bool(extract.CONTACT_LINK.search(sub)))
    res["status"] = "ok"
    res["elapsed"] = round(time.time() - started, 1)
    return res


def _absorb(res, data, page_url, is_contact):
    res["pages"].append(page_url)
    if is_contact and extract.CONTACT_PAGE_LINK.search(urlsplit(page_url).path) and page_url not in res["contact_pages"]:
        res["contact_pages"].append(page_url)
    if is_contact and data.get("has_contact_form") and page_url not in res["contact_forms"]:
        res["contact_forms"].append(page_url)
    for candidate in data.get("contact_pages", []):
        if _same_site(candidate, res["final_url"] or res["url"]) and candidate not in res["contact_pages"]:
            res["contact_pages"].append(candidate)
    res["closed_hint"] = res["closed_hint"] or data["closed_hint"]
    if data.get("students") and (res["students"] or 0) < data["students"]:
        res["students"] = data["students"]
        res["students_page"] = page_url
    site = extract.registrable(_host(res["final_url"] or res["url"]))
    for email, info in data["emails"].items():
        cur = res["emails"].setdefault(email, {"weight": 0, "source_url": page_url})
        w = info["weight"] + (1 if is_contact else 0)
        domain = email.rsplit("@", 1)[1]
        if extract.registrable(domain) == site:
            w += 3
        elif domain in extract.FREE_MAIL:
            w += 1  # most Kenyan schools use a Gmail or Yahoo address
        else:
            w -= 3  # a third party's address (a web designer, a sponsor, the county office)
            cur["third_party"] = True
        if extract.email_role(email) in ("principal", "office", "general", "admissions"):
            w += 2
        cur["weight"] += w
    for phone, info in data["phones"].items():
        cur = res["phones"].setdefault(phone, {"weight": 0, "source_url": page_url, "label": info.get("label")})
        cur["weight"] += info["weight"] + (1 if is_contact else 0)
        if info.get("label"):
            cur["label"] = info["label"]
    for addr, weight in data["addresses"].items():
        cur = res["addresses"].setdefault(addr, {"weight": 0, "source_url": page_url})
        cur["weight"] += weight + (1 if is_contact else 0)
    for kind, url in data["socials"].items():
        if kind not in res["socials"]:
            res["socials"][kind] = url
            res["social_pages"][kind] = page_url
    for name, info in data["people"].items():
        cur = res["people"].get(name)
        if not cur or cur["rank"] < info["rank"]:
            res["people"][name] = dict(info, source_url=page_url)


def save(conn, school_id, res, ts=None):
    """Write one crawl result. Runs on the main thread."""
    ts = ts or db.now()
    status = res["status"]
    fields = {"enrich_status": status, "enrich_error": res.get("error"), "enriched_at": ts}
    if status == "social":
        fields["enrich_status"] = "no_site"
    if status == "ok":
        fields.update(site_title=res["title"] or None, site_description=res["description"] or None)
        conn.execute("UPDATE contacts SET active=0 WHERE school_id=? AND source='web' AND kind!='website'",
                     (school_id,))
        final = res.get("final_url")
        if final and _host(final) != _host(res["url"]):
            db.upsert_contact(conn, school_id, "website", final.rstrip("/"), "web",
                              label="redirected", source_url=res["url"], score=2, ts=ts)
        for email, info in sorted(res["emails"].items(), key=lambda kv: -kv[1]["weight"])[:6]:
            if info["weight"] < 1:
                continue
            label = "other domain" if info.get("third_party") else extract.email_role(email)
            db.upsert_contact(conn, school_id, "email", email, "web", label=label,
                              source_url=info["source_url"], score=min(info["weight"], 20), ts=ts)
        for phone, info in sorted(res["phones"].items(), key=lambda kv: -kv[1]["weight"])[:5]:
            score = info["weight"] - (8 if info.get("label") == "fax" else 0)
            db.upsert_contact(conn, school_id, "phone", phone, "web", label=info.get("label"),
                              source_url=info["source_url"], score=score, ts=ts)
        for addr, info in sorted(res["addresses"].items(), key=lambda kv: -kv[1]["weight"])[:2]:
            db.upsert_contact(conn, school_id, "address", addr, "web", source_url=info["source_url"],
                              score=info["weight"], ts=ts)
        for kind, url in res["socials"].items():
            db.upsert_contact(conn, school_id, kind, url, "web",
                              source_url=res.get("social_pages", {}).get(kind, res.get("final_url")), score=1, ts=ts)
        for url in res["contact_pages"][:3]:
            db.upsert_contact(conn, school_id, "contact_page", url, "web", source_url=url, score=1, ts=ts)
        for url in res["contact_forms"][:2]:
            db.upsert_contact(conn, school_id, "contact_form", url, "web", source_url=url, score=2, ts=ts)
        school = conn.execute("SELECT name, county, town, extra FROM schools WHERE id=?", (school_id,)).fetchone()
        context = f"{school['name']} {school['county'] or ''} {school['town'] or ''}" if school else ""
        kept = 0
        for name, info in sorted(res["people"].items(), key=lambda kv: -kv[1]["rank"]):
            name = extract.clean_person(name, context)
            if not name or kept >= 5:
                continue
            db.upsert_contact(conn, school_id, "person", name, "web", label=info["title"],
                              source_url=info.get("source_url"), score=info["rank"], ts=ts)
            kept += 1
        if res.get("students") and school:
            extra = json.loads(school["extra"] or "{}")
            extra["website_students"] = {"n": res["students"], "source_url": res.get("students_page")}
            fields["extra"] = json.dumps(extra)
        if res.get("closed_hint"):
            fields["business_status"] = "POSSIBLY_CLOSED"
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE schools SET {sets} WHERE id=?", (*fields.values(), school_id))
    db.refresh_primary(conn, school_id)
    db.index_one(conn, school_id)


def select_targets(conn, counties=None, stale_days=None, limit=None, school_ids=None, missing_email=False):
    where = ["s.website IS NOT NULL"]
    params = []
    if missing_email:
        where.append("s.email IS NULL")
    if school_ids:
        where.append(f"s.id IN ({','.join('?' * len(school_ids))})")
        params += list(school_ids)
    else:
        if stale_days is None:
            where.append("s.enriched_at IS NULL")
        else:
            where.append("(s.enriched_at IS NULL OR s.enriched_at < ?)")
            params.append(db.now() - stale_days * 86400)
        if counties:
            where.append(f"s.county_code IN ({','.join('?' * len(counties))})")
            params += list(counties)
    q = f"""SELECT s.id, s.website FROM schools s WHERE {' AND '.join(where)}
            ORDER BY s.enriched_at IS NOT NULL, s.enriched_at, (s.levels & 8) DESC"""
    if limit:
        q += f" LIMIT {int(limit)}"
    return conn.execute(q, params).fetchall()


def run(conn, counties=None, stale_days=None, limit=None, workers=16, school_ids=None, missing_email=False):
    conn.execute("UPDATE schools SET enrich_status='no_site' WHERE website IS NULL AND enrich_status IS NULL")
    conn.commit()
    targets = select_targets(conn, counties, stale_days, limit, school_ids, missing_email)
    total = len(targets)
    if not total:
        log("  nothing to crawl")
        return {"crawled": 0}
    log(f"  crawling {total:,} school websites with {workers} workers")
    counts = {}
    done = 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(crawl_site, t["website"]): t["id"] for t in targets}
        for fut in as_completed(futs):
            school_id = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {"status": "error", "error": f"{type(e).__name__}: {e}"[:200], "url": ""}
            save(conn, school_id, res)
            conn.commit()  # commit each school so the CRM can write while a crawl runs
            counts[res["status"]] = counts.get(res["status"], 0) + 1
            done += 1
            if done % 25 == 0 or done == total:
                rate = done / max(time.time() - started, 1)
                eta = (total - done) / rate if rate else 0
                log(f"  {done:,}/{total:,}  " + "  ".join(f"{k}:{v}" for k, v in sorted(counts.items()))
                    + f"  ~{eta / 60:.0f} min left")
    conn.commit()
    return {"crawled": total, **counts}
