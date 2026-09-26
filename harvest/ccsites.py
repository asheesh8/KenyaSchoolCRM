"""School websites from Common Crawl's index of .sc.ke and .ac.ke hosts.

Common Crawl (a public web archive) lists every .sc.ke (schools) and .ac.ke
(academic) host it has seen. Each site's home page is read, and the site is
attached to the directory school whose distinctive name words all appear in
the page's title and opening text; if two schools fit equally, it's skipped.
Then `crawl` reads the sites for emails, phones and the principal.
"""

import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from . import config, db, discover, eeg, extract, levels, net
from .net import log

INDEXES = ("CC-MAIN-2026-39", "CC-MAIN-2026-30")
SCHOOLISH = re.compile(r"school|schl|sch$|academy|acad|college|high|sec|primary|pri$|kinder|nursery|montessori|junior|institute|poly|tvc|ttc|vtc|educ|learn|kids|prep", re.I)


def hosts():
    cache = config.CACHE / "cc" / "hosts.txt"
    if not cache.exists():
        found = set()
        for idx in INDEXES:
            for tld in ("sc.ke", "ac.ke"):
                base = f"https://index.commoncrawl.org/{idx}-index?url=*.{tld}&output=json"
                pages = net.request_json(base + "&showNumPages=true").get("pages", 0)
                for p in range(pages):
                    for line in net.request(f"{base}&fl=url&page={p}", timeout=180).decode().splitlines():
                        try:
                            h = urllib.parse.urlsplit(json.loads(line)["url"]).hostname or ""
                        except ValueError:
                            continue
                        found.add(h[4:] if h.startswith("www.") else h)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("\n".join(sorted(found)))
    domains = {extract.registrable(h) for h in cache.read_text().split() if h}
    out = {d for d in domains if d.endswith((".sc.ke", ".ac.ke"))}
    # other Kenyan domains whose own name says school (".co.ke", ".or.ke"), from the filtered index pulls
    for f in (config.CACHE / "cc").glob("more_*.jsonl"):
        for line in f.read_text(errors="replace").splitlines():
            try:
                h = urllib.parse.urlsplit(json.loads(line)["url"]).hostname or ""
            except (ValueError, KeyError):
                continue
            d = extract.registrable(h)
            if SCHOOLISH.search(d.split(".")[0]):
                out.add(d)
    return sorted(out)


def _home(domain):
    for url in (f"https://{domain}/", f"https://www.{domain}/", f"http://{domain}/"):
        if not net.robots_allows(url):
            return None
        page = net.fetch_raw(url, timeout=12)
        if page.ok:
            return page
    return None


def run(conn, workers=16):
    have = {extract.registrable(urllib.parse.urlsplit(r[0]).hostname or "") for r in
            conn.execute("SELECT value FROM contacts WHERE kind='website'")}
    todo = [d for d in hosts() if d not in have]
    log(f"  {len(todo):,} school and college domains not yet on file")
    index = {}
    names = {}
    for r in conn.execute("SELECT id, name FROM schools"):
        toks = levels.tokens(r["name"])
        if toks:
            names[r["id"]] = toks
            for t in toks:
                index.setdefault(t, set()).add(r["id"])
    with ThreadPoolExecutor(workers) as pool:
        pages = list(zip(todo, pool.map(_home, todo)))
    stats = {"domains": len(todo), "answered": 0, "matched": 0, "ambiguous": 0, "added": 0}
    placer = eeg.Places(conn)
    ts = db.now()
    for domain, page in pages:
        if not page:
            continue
        stats["answered"] += 1
        data = extract.extract(page.html, page.final_url)
        if data["parked"]:
            continue
        hay = re.sub(r"[^A-Z0-9 ]+", " ", " ".join((data["title"], data["description"], data["visible_text"][:1500])).upper().replace("'", ""))
        # the school's name must be in the site's own title (or its domain), not just somewhere on the page
        title = re.sub(r"[^A-Z0-9 ]+", " ", (data["title"] or "").upper().replace("'", ""))
        words = set(title.split())
        label = domain.split(".")[0].upper().replace("-", "")
        cands = set()
        for w in words:
            cands |= index.get(w, set())
        cands |= {sid_ for t, ids in index.items() if len(t) >= 5 and t in label for sid_ in ids} if len(label) >= 6 else set()
        fits = [(len(names[s]), s) for s in cands
                if sum(len(t) for t in names[s]) >= 5 and all(t in words or (len(t) >= 4 and t in label) for t in names[s])]
        if not fits:
            # a real school the directory doesn't have yet: add it, placed by the address on its own site
            title = re.split(r"\s[|\-–—:]\s", data["title"] or "")[0].strip()
            boxes = extract.POBOX_RE.findall(data["visible_text"])
            county = placer.county(*[b[2] for b in boxes if b[2]], data["visible_text"][:3000])
            if (county and 3 <= len(title) <= 80 and re.search(r"school|academy|college|institute|polytechnic|kindergarten|montessori|high", title, re.I)
                    and discover.page_names_school(page, title)):
                area = conn.execute("SELECT name FROM areas WHERE code=?", (county,)).fetchone()
                mask = levels.levels_from_name(title) or levels.PRIMARY
                sid = conn.execute("""INSERT INTO schools(name, levels, ownership, county_code, county, sources, created_at,
                                        updated_at) VALUES (?,?,?,?,?,?,?,?)""",
                                   (levels.display_name(title), mask, "private", county, area["name"], '["web"]', ts, ts)).lastrowid
                db.upsert_contact(conn, sid, "website", page.final_url.rstrip("/"), "search", label="found in web archive",
                                  source_url=page.final_url, score=1, ts=ts)
                db.refresh_primary(conn, sid)
                stats["added"] += 1
            continue
        top = max(n for n, _ in fits)
        best = [s for n, s in fits if n == top]
        if len(best) > 1:
            # same name in several places: keep the one whose county, constituency or town the page mentions
            where = {}
            for sid_ in best:
                r = conn.execute("SELECT county, subcounty, town, location, levels FROM schools WHERE id=?", (sid_,)).fetchone()
                places = {w for v in (r["county"], r["subcounty"], r["town"], r["location"]) if v
                          for w in re.sub(r"[^A-Z ]", " ", v.upper()).split() if len(w) > 3}
                score = len(places & words) + (1 if domain.endswith(".ac.ke") and r["levels"] & (8 | 16 | 32 | 64) else 0)
                where[sid_] = score
            ranked = sorted(best, key=lambda x: -where[x])
            best = ranked[:1] if where[ranked[0]] > where[ranked[1]] else best
        page_county = None
        if len(best) != 1 or not fits:
            boxes = extract.POBOX_RE.findall(data["visible_text"])
            page_county = placer.county(*[b[2] for b in boxes if b[2]], data["title"], data["visible_text"][:3000])
        if len(best) > 1 and len({frozenset(names[x]) for x in best}) == 1:
            # the same school twice in the directory: keep the record with a map position
            best = sorted(best, key=lambda x: conn.execute("SELECT lat IS NULL FROM schools WHERE id=?", (x,)).fetchone()[0])[:1]
        if len(best) > 1 and page_county:
            inside = [s_ for s_ in best if conn.execute("SELECT county_code FROM schools WHERE id=?", (s_,)).fetchone()[0] == page_county]
            if len(inside) == 1:
                best = inside
        if len(best) != 1:
            stats["ambiguous"] += 1
            continue
        sid = best[0]
        if not discover.page_names_school(page, conn.execute("SELECT name FROM schools WHERE id=?", (sid,)).fetchone()[0]):
            continue
        db.upsert_contact(conn, sid, "website", page.final_url.rstrip("/"), "search", label="found in web archive",
                          source_url=page.final_url, score=1, ts=ts)
        conn.execute("UPDATE schools SET enriched_at=NULL, enrich_status=NULL WHERE id=?", (sid,))
        db.refresh_primary(conn, sid)
        stats["matched"] += 1
    conn.commit()
    return stats
