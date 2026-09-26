"""Secondary-school emails and phones from Education News Hub's school profiles.

educationnewshub.co.ke has a profile page for about 1,900 secondary schools
("... contacts, location, fees ..."). Where a page shows the school's email or
phone in plain text, it's recorded against the matching directory school. Pages
that hide the address behind Cloudflare's email protection are left alone.

Pages come from the site's sitemaps, are cached in data/cache/enh/, and are
fetched one every two seconds (robots.txt allows them).
"""

import hashlib
import html as htmllib
import re
import time

from . import config, db, extract, levels, net, osm
from .net import log

URL_RE = re.compile(r"https://educationnewshub\.co\.ke/[a-z0-9-]*(?:school|high)[a-z0-9-]*contact[a-z0-9-]*/$")
OWN_DOMAINS = re.compile(r"educationnewshub|sentry|wordpress|gravatar|example\.|@education\.go\.ke|@tsc\.go\.ke|@knec\.ac\.ke", re.I)


def urls():
    cache = config.CACHE / "enh" / "all.txt"
    if not cache.exists():
        index = net.fetch_raw("https://educationnewshub.co.ke/sitemap_index.xml").html
        found = []
        for sm in re.findall(r"<loc>([^<]*post-sitemap\d*\.xml)</loc>", index):
            time.sleep(0.5)
            found += re.findall(r"<loc>([^<]*)</loc>", net.fetch_raw(sm).html)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("\n".join(found))
    return sorted({u.strip() for u in cache.read_text().splitlines() if URL_RE.match(u.strip())})


def _get(url):
    path = config.CACHE / "enh" / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    if not net.robots_allows(url):
        return ""
    time.sleep(2)
    page = net.fetch_raw(url, timeout=30, max_bytes=3_000_000)
    if not page.ok:
        return ""
    path.write_text(page.html, encoding="utf-8")
    return page.html


def school_name(page_html, url):
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page_html, re.S)
    title = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(1))) if m else url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
    # "Kiambu High School's KCSE results, KNEC code, ..." / "Alliance Girls High Senior Schools History, ..."
    title = re.split(r"[’']s\b|:|;|,|\ball details\b|\s[-–|]\s|\bKCSE\b|\bCBE\b|\bFull Details\b|\bHistory\b|\bSenior Schools?\b", title, flags=re.I)[0]
    title = re.sub(r"\bSchools\b", "School", title, flags=re.I)
    return " ".join(title.split())


def parse(page_html):
    i = page_html.find("entry-content")
    body = page_html[i:] if i >= 0 else page_html
    # stop where the article ends and the site's lists of other posts begin. Only the visible
    # article is read: the page's hidden search-engine copy isn't used to get round protected emails.
    body = re.split(r'class="[^"]*(?:related|jp-relatedposts|post-navigation|comments-area|sidebar)', body, maxsplit=1)[0]
    body = re.sub(r"<script.*?</script>", " ", body, flags=re.S)
    body = re.sub(r"<(?:a|span)[^>]*(?:data-cfemail|email-protection)[^>]*>.*?</(?:a|span)>", " ", body, flags=re.S)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", " ", body, flags=re.S)))
    text = text.replace(" ", " ")
    emails = []
    for raw in extract.EMAIL_RE.findall(text):
        e = extract.clean_email(raw)
        if e and not OWN_DOMAINS.search(e) and e not in emails:
            emails.append(e)
    phones = []
    for m in extract.PHONE_RE.finditer(text):
        p = extract.normalize_phone(m.group(0))
        if p and p not in phones:
            phones.append(p)
    m = re.search(r"\b(?:in|of)\s+([A-Z][a-z]+(?:[ -][A-Z][a-z]+)?)\s+County\b", text)
    return emails[:3], phones[:3], (m.group(1) if m else None)


def ingest(conn, limit=None):
    counties = {r["name"].lower().replace("-", " "): r["code"] for r in conn.execute("SELECT code, name FROM areas WHERE kind='county'")}
    index = {}
    rows = {}
    for r in conn.execute("SELECT id, name, county_code FROM schools WHERE levels & 8"):
        toks = levels.tokens(r["name"])
        rows[r["id"]] = (toks, r["county_code"])
        for t in toks:
            index.setdefault(t, set()).add(r["id"])
    todo = urls()[:limit] if limit else urls()
    cached = sum(1 for u in todo if (config.CACHE / "enh" / (hashlib.sha1(u.encode()).hexdigest()[:16] + ".html")).exists())
    log(f"  {len(todo):,} school profiles ({cached:,} already downloaded; the rest at one every 2 seconds)")
    stats = {"pages": 0, "matched": 0, "emails": 0, "phones": 0, "unmatched": 0}
    for n, url in enumerate(todo, 1):
        page = _get(url)
        if not page:
            continue
        stats["pages"] += 1
        emails, phones, county_name = parse(page)
        if not emails and not phones:
            continue
        name = school_name(page, url)
        county = counties.get((county_name or "").lower().replace("-", " "))
        toks = levels.tokens(name)
        cands = set()
        for t in toks:
            cands |= index.get(t, set())
        best = None
        for sid in cands:
            stoks, scounty = rows[sid]
            if county and scounty and scounty != county:
                continue
            sc = osm.name_score(toks, stoks)
            need = 0.75 if county else 1.0
            if sc >= need and (best is None or sc > best[0]):
                best = (sc, sid)
        if not best:
            stats["unmatched"] += 1
            continue
        sid = best[1]
        stats["matched"] += 1
        ts = db.now()
        for e in emails:
            db.upsert_contact(conn, sid, "email", e, "list", label=extract.email_role(e), source_url=url, score=3, ts=ts)
            stats["emails"] += 1
        for p in phones:
            db.upsert_contact(conn, sid, "phone", p, "list", source_url=url, score=2, ts=ts)
            stats["phones"] += 1
        cur = conn.execute("SELECT sources FROM schools WHERE id=?", (sid,)).fetchone()
        conn.execute("UPDATE schools SET sources=? WHERE id=?", (db.add_sources(cur["sources"], "enh"), sid))
        db.refresh_primary(conn, sid)
        conn.commit()
        if n % 100 == 0:
            log(f"  {n:,}/{len(todo):,} pages, {stats['matched']:,} schools matched, {stats['emails']:,} emails")
    conn.commit()
    return stats
