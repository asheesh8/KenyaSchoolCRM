"""OpenStreetMap: schools, kindergartens, colleges and universities mapped in Kenya.

OSM adds what the Ministry list lacks: phone numbers, emails, websites, head
teachers' names, enrolment and teacher counts (from community surveys such as
Map Kibera), and thousands of schools opened since 2010. Each map feature is
matched to a Ministry school within 2 km whose name agrees; the rest become new
records. Map data is (c) OpenStreetMap contributors, ODbL.
"""

import json
import math
import re
import time
import urllib.parse

from . import areas, config, db, extract, levels, net
from .net import log

QUERY = """[out:json][timeout:900];
(nwr["amenity"~"^(school|kindergarten|college|university)$"]({s},{w},{n},{e}););
out center tags;"""
MATCH_KM = 2.0


def fetch(max_age_days=7):
    path = config.CACHE / "osm_overpass.json"
    if path.exists() and time.time() - path.stat().st_mtime < max_age_days * 86400:
        return json.loads(path.read_text())["elements"]
    s, w, n, e = config.KENYA_BBOX
    q = QUERY.format(s=s, w=w, n=n, e=e)
    last = None
    for ep in config.OVERPASS_ENDPOINTS:
        try:
            log(f"  asking {urllib.parse.urlsplit(ep).netloc} for every school in Kenya (a few minutes)")
            body = net.request(ep, data=urllib.parse.urlencode({"data": q}), timeout=960, retries=2, backoff=20,
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
            data = json.loads(body)
            if data.get("remark") and "error" in data["remark"].lower():
                raise ValueError(data["remark"][:200])
            config.ensure_dirs()
            path.write_bytes(body)
            return data["elements"]
        except Exception as ex:  # busy server, timeout: try the next one
            last = ex
            log(f"  {urllib.parse.urlsplit(ep).netloc} failed: {str(ex)[:120]}")
    if path.exists():
        log("  using the previous OSM download")
        return json.loads(path.read_text())["elements"]
    raise SystemExit(f"Every Overpass server failed ({last}). Try again later, or set HARVEST_OVERPASS.")


def _int(v, lo=1, hi=20000):
    m = re.search(r"\d[\d,]*", str(v or ""))
    if not m:
        return None
    n = int(m.group(0).replace(",", ""))
    return n if lo <= n <= hi else None


OWNERSHIP = {"government": ("public", "government"), "central_government_deb": ("public", "government"),
             "public": ("public", None), "local_government_authority": ("public", "local_authority"),
             "religious": (None, "religious"), "religious_organization": (None, "religious"),
             "community": ("public", "community"), "cbo": ("private", "ngo"), "ngo": ("private", "ngo"),
             "private": ("private", "private"), "private_for_profit": ("private", "private"),
             "private_non_profit": ("private", "ngo")}
GENDER = {"mixed": "mixed", "female": "girls", "girls": "girls", "girls_only": "girls", "male": "boys",
          "boys": "boys", "boys_only": "boys"}


def parse(el):
    t = el.get("tags") or {}
    name = (t.get("name") or t.get("name:en") or "").strip()
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    if not name or lat is None or len(name) < 3 or re.fullmatch(r"(?i)school|shule|primary|nursery", name):
        return None
    otype = (t.get("operator:type") or "").lower().strip()
    ownership, sponsor = OWNERSHIP.get(otype, (None, None))
    faith = (OSM_FAITH(t) or levels.faith_from_name(f"{name} {t.get('operator') or ''}"))
    gender = GENDER.get((t.get("school:gender") or t.get("education:gender_type") or t.get("gender") or "").lower())
    operate = (t.get("education:operate_as") or "").lower()
    boarding = ("day_boarding" if "day_and_boarding" in operate else "boarding" if "boarding" in operate
                else "day" if "day" in operate else None)
    mask = levels.osm_levels(t)
    etype = (t.get("education:type") or "").lower()
    if "pre_primary" in etype or "nursery" in etype or "day_care" in etype or "daycare" in etype:
        mask |= levels.ECDE
    if "primary" in etype.replace("pre_primary", ""):
        mask |= levels.PRIMARY
    if "secondary" in etype:
        mask |= levels.SENIOR
    if "vocational" in etype:
        mask |= levels.TVET
    reg = (t.get("education:government_registered") or "").lower()
    if "apbet" in reg:
        mask |= levels.NONFORMAL
    extra = {}
    for k, label in (("education:fees_per_year", "fees_per_year"), ("education:fees", "fees"),
                     ("education:curriculum", "curriculum"), ("education:exam_center", "exam_centre"),
                     ("education:program_feeding", "feeding_programme"), ("opening_hours", "hours"),
                     ("electricity:operational_status", "electricity"), ("water_source", "water"),
                     ("description", "description"), ("education:government_registered", "registered_with"),
                     ("operator", "operator"), ("check_date", "surveyed")):
        if t.get(k):
            extra[label] = t[k][:300]
    contacts = []
    for key in ("contact:phone", "phone", "contact:mobile", "mobile"):
        for raw in re.split(r"[;,/]", t.get(key) or ""):
            ph = extract.normalize_phone(raw)
            if ph:
                contacts.append(("phone", ph, None))
    for key in ("contact:email", "email"):
        for raw in re.split(r"[;,\s]", t.get(key) or ""):
            e = extract.clean_email(raw)
            if e:
                contacts.append(("email", e, extract.email_role(e)))
    for key in ("website", "contact:website", "url", "contact:facebook", "facebook"):
        for raw in re.split(r"[;\s]", t.get(key) or ""):
            contacts += url_contacts(raw)
    head = (t.get("education:school_head") or "").strip()
    if head and 3 < len(head) < 60 and not re.search(r"\d|@", head):
        title = "Principal" if mask & (levels.SENIOR | levels.TVET | levels.TTC) else "Head teacher"
        contacts.append(("person", re.sub(r"^(?:Mr|Mrs|Ms|Madam|Dr)\.?\s*", "", head).strip(), title))
    addr = t.get("contact:address") or t.get("addr:full")
    m = extract.POBOX_RE.search(addr or "")
    if m:
        contacts.append(("address", extract.format_pobox(m.group(1), m.group(2), m.group(3)), None))
    town = t.get("addr:city") or t.get("addr:town") or t.get("addr:village") or t.get("place:village")
    return {
        "osm_id": f"{el['type']}/{el['id']}", "name": levels.display_name(name), "raw_name": name,
        "lat": float(lat), "lon": float(lon), "levels": mask, "ownership": ownership, "sponsor": sponsor,
        "faith": faith, "gender": gender or levels.gender_from_name(name),
        "boarding": boarding or levels.boarding_from_name(name),
        "special_needs": levels.special_from_name(name) or int((t.get("education:program_special_needs") or "") == "yes"),
        "town": town.strip().title() if town else None,
        "students": _int(t.get("education:students")) or _int(t.get("student_count")),
        "students_female": _int(t.get("education:students_female"), 0),
        "students_male": _int(t.get("education:students_male"), 0),
        "teachers": _int(t.get("education:teachers"), 1, 500),
        "capacity": _int(t.get("capacity")),
        "wikidata": t.get("wikidata"), "extra": extra, "contacts": contacts,
    }


def OSM_FAITH(t):
    rel = (t.get("religion") or "").lower()
    den = (t.get("denomination") or "").lower()
    if den in levels.OSM_DENOMINATION:
        return levels.OSM_DENOMINATION[den]
    if rel in levels.OSM_RELIGION:
        return levels.OSM_RELIGION[rel]
    if rel == "christian":
        return "Christian (other)"
    return None


def url_contacts(raw):
    url = extract.normalize_url(raw)
    if not url:
        return []
    for kind, rx in extract.SOCIAL_PATTERNS:
        if rx.match(url) and extract.social_profile_is_specific(kind, url):
            return [(kind, extract.normalize_social_profile(kind, url), None)]
    if re.search(r"facebook\.com|instagram\.com|twitter\.com|youtube\.com|wa\.me|google\.com/maps", url, re.I):
        return []
    return [("website", url.rstrip("/"), None)]


def _km(a_lat, a_lon, b_lat, b_lon):
    return math.hypot((a_lat - b_lat) * 111.0, (a_lon - b_lon) * 111.0 * math.cos(math.radians(a_lat)))


class SchoolIndex:
    """Nearby existing schools, by a 0.02-degree grid."""

    STEP = 0.02

    def __init__(self, conn):
        self.grid = {}
        self.rows = {}
        for r in conn.execute("SELECT id, name, lat, lon, levels, osm_id FROM schools WHERE lat IS NOT NULL"):
            self.add(dict(r))

    def add(self, r):
        r["tokens"] = levels.tokens(r["name"])
        self.rows[r["id"]] = r
        self.grid.setdefault((math.floor(r["lat"] / self.STEP), math.floor(r["lon"] / self.STEP)), []).append(r["id"])

    def near(self, lat, lon, km):
        span = math.ceil(km / (self.STEP * 111)) + 1
        gy, gx = math.floor(lat / self.STEP), math.floor(lon / self.STEP)
        for dy in range(-span, span + 1):
            for dx in range(-span, span + 1):
                for sid in self.grid.get((gy + dy, gx + dx), ()):
                    r = self.rows[sid]
                    d = _km(lat, lon, r["lat"], r["lon"])
                    if d <= km:
                        yield r, d


def name_score(a_tokens, b_tokens):
    """1.0 for the same name; a short name wholly inside a longer one scores
    0.75 (0.6 for a single distinctive word), partial overlaps score lower."""
    if not a_tokens or not b_tokens:
        return 0.0
    common = a_tokens & b_tokens
    if not common:
        # tolerate one-letter spelling differences ("KIRINYGALIA" / "KIRINYAGALIA")
        close = sum(1 for x in a_tokens for y in b_tokens if len(x) > 4 and _one_edit(x, y))
        return 0.8 * close / max(len(a_tokens), len(b_tokens))
    jaccard = len(common) / len(a_tokens | b_tokens)
    smaller = a_tokens if len(a_tokens) <= len(b_tokens) else b_tokens
    if common == smaller:
        if len(smaller) >= 2:
            return max(jaccard, 0.75)
        return max(jaccard, 0.6 if len(next(iter(smaller))) >= 5 else 0.4)
    return jaccard


def _one_edit(a, b):
    if abs(len(a) - len(b)) > 1 or a == b:
        return a == b
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    return any(b[:i] + b[i + 1:] == a for i in range(len(b)))


def best_match(index, rec):
    toks = levels.tokens(rec["raw_name"])
    best = None
    for r, d in index.near(rec["lat"], rec["lon"], MATCH_KM):
        if rec["levels"] and r["levels"] and not rec["levels"] & r["levels"]:
            # a secondary school and the primary school it's named after are different schools
            basic = levels.ECDE | levels.PRIMARY | levels.JUNIOR | levels.NONFORMAL
            if not (rec["levels"] & basic and r["levels"] & basic):
                continue
        s = name_score(toks, r["tokens"])
        if s < 0.6 or (s < 0.85 and d > 0.8):
            continue
        score = s - d / (MATCH_KM * 4)
        if best is None or score > best[0]:
            best = (score, r)
    return best[1] if best else None


def ingest(conn):
    loc = areas.locator()
    elements = fetch()
    log(f"  {len(elements):,} map features")
    index = SchoolIndex(conn)
    stats = {"features": len(elements), "matched": 0, "new": 0, "outside": 0, "skipped": 0}
    ts = db.now()
    for el in elements:
        rec = parse(el)
        if not rec:
            stats["skipped"] += 1
            continue
        if not loc.in_kenya(rec["lon"], rec["lat"]):
            stats["outside"] += 1
            continue
        existing = conn.execute("SELECT id FROM schools WHERE osm_id=?", (rec["osm_id"],)).fetchone()
        target = existing["id"] if existing else None
        if target is None:
            m = best_match(index, rec)
            target = m["id"] if m else None
        if target is None:
            where = loc.locate(rec["lon"], rec["lat"])
            cur = conn.execute(
                """INSERT INTO schools(name, levels, ownership, sponsor, faith, gender, boarding, special_needs,
                     county_code, county, subcounty_code, subcounty, pop_density, setting, town, lat, lon,
                     students, students_female, students_male, teachers, capacity, osm_id, wikidata, sources, extra,
                     created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rec["name"], rec["levels"], rec["ownership"], rec["sponsor"], rec["faith"], rec["gender"],
                 rec["boarding"], rec["special_needs"], where["county_code"], where["county"],
                 where["subcounty_code"], where["subcounty"],
                 round(where["density"]) if where["density"] is not None else None, areas.setting(where["density"]),
                 rec["town"], rec["lat"], rec["lon"], rec["students"], rec["students_female"],
                 rec["students_male"], rec["teachers"], rec["capacity"], rec["osm_id"], rec["wikidata"],
                 json.dumps(["osm"]), json.dumps({"osm": rec["extra"]} if rec["extra"] else {}), ts, ts))
            target = cur.lastrowid
            index.add({"id": target, "name": rec["raw_name"], "lat": rec["lat"], "lon": rec["lon"],
                       "levels": rec["levels"], "osm_id": rec["osm_id"]})
            stats["new"] += 1
        else:
            _update(conn, target, rec)
            stats["matched"] += 1
        for kind, value, label in rec["contacts"]:
            db.upsert_contact(conn, target, kind, value, "osm", label=label,
                              source_url=f"https://www.openstreetmap.org/{rec['osm_id']}", score=1, ts=ts)
        db.refresh_primary(conn, target)
        if (stats["matched"] + stats["new"]) % 2000 == 0:
            conn.commit()
            log(f"  {stats['matched']:,} matched, {stats['new']:,} new")
    levels.apply_all_grades(conn)
    conn.commit()
    stats["levels_reconciled"] = reconcile_levels(conn)
    return stats


def combine_levels(known, from_map, map_name):
    """The map may add pre-primary and Junior School to a school whose levels are
    known; it adds secondary or post-secondary only when its name says so, because
    many Kenyan primaries are mapped with isced:level=2;3;4."""
    if not known:
        return from_map
    allowed = levels.ECDE | levels.JUNIOR | (levels.levels_from_name(map_name) & ~levels.PRIMARY)
    return known | (from_map & allowed)


def reconcile_levels(conn):
    """Re-derive levels for Ministry schools that were matched to a map feature."""
    elements = {f"{e['type']}/{e['id']}": e for e in fetch(max_age_days=3650)}
    fixed = 0
    for r in conn.execute("SELECT id, levels, osm_id, extra FROM schools WHERE osm_id IS NOT NULL AND moe_keys != '[]'").fetchall():
        units = json.loads(r["extra"] or "{}").get("moe_units") or []
        known = 0
        for u in units:
            known |= levels.moe_level(u.get("level"), u.get("name"))
        el = elements.get(r["osm_id"])
        if not known or not el:
            continue
        rec = parse(el)
        new = combine_levels(known, rec["levels"], rec["raw_name"]) if rec else known
        if new != r["levels"]:
            conn.execute("UPDATE schools SET levels=? WHERE id=?", (new, r["id"]))
            fixed += 1
    levels.apply_all_grades(conn)
    conn.commit()
    return fixed


def _update(conn, school_id, rec):
    cur = conn.execute("SELECT * FROM schools WHERE id=?", (school_id,)).fetchone()
    fields = {}
    for col in ("ownership", "sponsor", "gender", "boarding", "town", "students", "students_female",
                "students_male", "teachers", "capacity", "wikidata"):
        if cur[col] in (None, "") and rec.get(col) not in (None, ""):
            fields[col] = rec[col]
    if rec["faith"] and cur["faith"] in (None, "Religious (unspecified)"):
        fields["faith"] = rec["faith"]
    if rec["students"] and cur["students"] and rec["students"] != cur["students"]:
        fields["students"] = rec["students"]  # the map survey is newer than the Ministry list
    if cur["osm_id"] is None:
        fields["osm_id"] = rec["osm_id"]
    fields["levels"] = combine_levels(cur["levels"] or 0, rec["levels"], rec["raw_name"])
    fields["special_needs"] = max(cur["special_needs"], rec["special_needs"])
    fields["sources"] = db.add_sources(cur["sources"], "osm")
    if rec["extra"]:
        extra = json.loads(cur["extra"] or "{}")
        extra.setdefault("osm", {}).update(rec["extra"])
        fields["extra"] = json.dumps(extra)
    fields["updated_at"] = db.now()
    conn.execute(f"UPDATE schools SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                 (*fields.values(), school_id))
