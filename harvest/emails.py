"""Find school emails with a web search API (needs BRAVE_API_KEY).

For each school without an email, search for its name, county and "email".
An address is kept only when the search result's own text names the school
(every distinctive word of its name appears within the same result) and the
address sits in that result, or when the address itself is built from the
school's name (makuenisec@gmail.com for Makueni Secondary). Results that
list many schools (directories, KCSE result tables) are skipped.

Brave Search API: free tier 2,000 queries a month; paid plans are billed per
1,000 queries. Start with --limit to see the hit rate before a big run.
"""

import re
import threading
import time
import urllib.parse

from . import config, db, extract, levels, net
from .net import log

_lock = threading.Lock()
_last = [0.0]


def _search(q):
    with _lock:
        wait = 1.05 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": q, "count": 10, "country": "KE", "extra_snippets": "true"})
    data = net.request_json(url, headers={"X-Subscription-Token": config.BRAVE_API_KEY, "Accept": "application/json"},
                            timeout=20, retries=2)
    return (data.get("web") or {}).get("results", [])


def _norm(text):
    return re.sub(r"[^A-Z0-9@. ]+", " ", (text or "").upper().replace("'", ""))


def emails_for(name, county):
    toks = levels.tokens(name)
    if not toks:
        return []
    slug = "".join(sorted(toks, key=len, reverse=True)[:1]).lower()
    found = {}
    for r in _search(f'"{name}" {county or ""} Kenya email'):
        blob = " ".join([r.get("title") or "", r.get("description") or ""] + (r.get("extra_snippets") or []))
        text = _norm(re.sub(r"<[^>]+>", " ", blob))
        if len(re.findall(r"\b(?:SCHOOL|SECONDARY|ACADEMY)\b", text)) > 6:
            continue  # a directory or results table listing many schools
        names_school = all(re.search(rf"\b{re.escape(t)}\b", text) for t in toks)
        for raw in extract.EMAIL_RE.findall(re.sub(r"<[^>]+>", " ", blob)):
            e = extract.clean_email(raw)
            if not e:
                continue
            local = re.sub(r"[^a-z]", "", e.split("@")[0])
            built_from_name = len(slug) >= 4 and slug in local
            if names_school or built_from_name:
                found.setdefault(e, r.get("url"))
    return list(found.items())[:2]


def run(conn, counties=None, limit=None, levels_arg=None):
    if not config.BRAVE_API_KEY:
        raise SystemExit("Set BRAVE_API_KEY (Brave Search API, https://brave.com/search/api/) to search for emails.")
    where = ["email IS NULL", "(email_searched_at IS NULL)"]
    params = []
    mask = 0
    for k in (levels_arg or "senior,tvet,ttc,university").split(","):
        mask |= levels.BY_KEY[k.strip()]
    where.append(f"levels & {mask}")
    if counties:
        where.append(f"county_code IN ({','.join('?' * len(counties))})")
        params += counties
    rows = conn.execute(f"SELECT id, name, county FROM schools WHERE {' AND '.join(where)} "
                        f"ORDER BY (leader IS NOT NULL) DESC, students DESC LIMIT {int(limit or 500)}", params).fetchall()
    log(f"  searching the web for emails of {len(rows):,} schools (about 1 per second)")
    found = 0
    for i, r in enumerate(rows, 1):
        try:
            hits = emails_for(r["name"], r["county"])
        except Exception as e:
            log(f"  search failed: {str(e)[:120]}")
            break
        ts = db.now()
        for email, url in hits:
            db.upsert_contact(conn, r["id"], "email", email, "search", label="found by web search", source_url=url,
                              score=1, ts=ts)
        conn.execute("UPDATE schools SET email_searched_at=? WHERE id=?", (ts, r["id"]))
        if hits:
            found += 1
            db.refresh_primary(conn, r["id"])
        conn.commit()
        if i % 50 == 0:
            log(f"  {i:,}/{len(rows):,} searched, {found:,} with an email")
    return {"searched": len(rows), "found": found}
