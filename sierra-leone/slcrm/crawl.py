"""Reads each known school website (home page plus a few contact / about / staff pages)
and records the emails, Sierra Leone phone numbers and named heads it publishes.

Polite: robots.txt honoured, public addresses only, a handful of pages per site.
"""

import html
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from . import db, levels
from .net import fetch_page, log

EMAIL = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?:\+|00)?232[\s\-().]*\d{2}[\s\-().]*\d{3}[\s\-().]*\d{3}|\b0\d{2}[\s\-]?\d{3}[\s\-]?\d{3}\b")
LEADER = re.compile(r"(?:(Principal|Head ?teacher|Headmaster|Headmistress|Proprietor|Proprietress|Vice[- ]Chancellor|"
                    r"Registrar|Director|Rector)\s*[:\-–]\s*((?:(?:Mr|Mrs|Ms|Dr|Rev|Revd|Fr|Sr|Prof|Alhaji)\.?\s+)?"
                    r"[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-.]+){1,3}))")
LINK = re.compile(r"""<a\s[^>]*href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.I | re.S)
SUBPAGE = re.compile(r"contact|about|staff|principal|head|admin|leadership|management|reach", re.I)
JUNK = re.compile(r"\.(png|jpe?g|gif|webp|svg)$|example\.|sentry|wixpress|@2x|domain\.com|email\.com", re.I)


def text_of(page):
    page = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", page)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def extract(page, url):
    """Emails, phones and named leaders from one HTML page."""
    out = {"emails": set(), "phones": set(), "people": set()}
    for m in re.findall(r"mailto:([^\"'?>\s]+)", page, re.I):
        e = levels.clean_email(urllib.parse.unquote(m))
        if e and not JUNK.search(e):
            out["emails"].add(e)
    txt = text_of(page)
    for m in EMAIL.findall(txt):
        e = levels.clean_email(m)
        if e and not JUNK.search(e):
            out["emails"].add(e)
    for m in PHONE.findall(txt):
        p = levels.clean_phone(m)
        if p:
            out["phones"].add(p)
    for role, name in LEADER.findall(" ".join(txt.split())):
        out["people"].add((name.strip(), role.strip().title()))
    return out


def crawl_site(site):
    found, pages = {"emails": set(), "phones": set(), "people": set()}, {}
    try:
        final, page = fetch_page(site)
    except Exception as e:
        return None, str(e)
    pages[final] = page
    links = []
    for href, label in LINK.findall(page):
        u = urllib.parse.urljoin(final, href)
        if urllib.parse.urlsplit(u).netloc == urllib.parse.urlsplit(final).netloc and \
                (SUBPAGE.search(href) or SUBPAGE.search(label)) and u not in pages and u not in links:
            links.append(u)
    for u in links[:4]:
        try:
            fu, p = fetch_page(u)
            pages[fu] = p
        except Exception:
            continue
    per = {}
    for u, p in pages.items():
        got = extract(p, u)
        for k in found:
            for v in got[k]:
                if v not in found[k]:
                    found[k].add(v)
                    per[(k, v)] = u
    return (found, per, final), None


def run(conn, limit=None, workers=8):
    rows = conn.execute("SELECT id, website FROM schools WHERE website IS NOT NULL ORDER BY id").fetchall()
    if limit:
        rows = rows[:limit]
    stats = {"sites": len(rows), "ok": 0, "failed": 0, "emails": 0, "phones": 0, "people": 0}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for row, (res, err) in zip(rows, ex.map(lambda r: crawl_site(r["website"]), rows)):
            if err:
                stats["failed"] += 1
                log(f"  {row['website']}: {err}")
                continue
            stats["ok"] += 1
            found, per, final = res
            domain = urllib.parse.urlsplit(final).netloc.lower().removeprefix("www.")
            t = db.now()
            for e in found["emails"]:
                conf = "high" if e.split("@")[-1].endswith(domain) else "medium"
                db.upsert_contact(conn, row["id"], "email", e, "web", source_url=per[("emails", e)], confidence=conf,
                                  ts=t)
                stats["emails"] += 1
            for p in found["phones"]:
                db.upsert_contact(conn, row["id"], "phone", p, "web", source_url=per[("phones", p)], ts=t)
                stats["phones"] += 1
            for name, role in found["people"]:
                db.upsert_contact(conn, row["id"], "person", name, "web", name, role, per[("people", (name, role))],
                                  ts=t)
                stats["people"] += 1
            db.refresh_primary(conn, row["id"])
            conn.commit()
    return stats
