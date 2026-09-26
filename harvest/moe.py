"""The Ministry of Education school list, the directory's backbone.

The 2010 edition (72,019 rows) lists each *teaching unit* separately: a village
school usually appears twice, once as its ECD centre and once as its primary
school, at the same coordinates. Rows are folded into one school when they
share a site and a name and belong together:

- ECD, primary, non-formal and special-unit rows join into one basic-education
  school (in Kenya the ECD centre is run by the primary school it sits in);
- secondary schools, colleges and universities stay separate, because they are
  separate institutions with their own principal, even when they share a
  compound and a name with a primary school.

If you save the 2017 World Bank / Ministry edition to data/cache/wb_schools.json
it is read too, and its rows fold into the same schools.
"""

import csv
import hashlib
import json
import math

from . import areas, config, db, levels, net, osm
from .net import log

BASIC = levels.ECDE | levels.PRIMARY | levels.JUNIOR | levels.NONFORMAL
NEAR_DEG = 0.004  # ~450 m: coordinates in the list are often rounded to a village centre


def _key(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _tier(mask):
    if not mask or mask & BASIC and not mask & ~BASIC:
        return "basic"
    if mask & levels.SENIOR:
        return "senior"
    return "post"


def _num(v):
    try:
        n = int(float(str(v).strip()))
        return n if 0 <= n < 500 else None
    except (TypeError, ValueError):
        return None


def read_2010():
    path = net.cached_download(config.MOE_SHEET_URL, "moe_schools_2010.csv", max_age_days=3650)
    with open(path, encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                lat, lon = float(r["Latitude"]), float(r["Longitude"])
            except (TypeError, ValueError):
                continue
            name = (r.get("Name") or "").strip()
            if not name:
                continue
            yield {
                "key": _key("moe2010", name, r.get("Level"), r["Latitude"], r["Longitude"]),
                "source": "moe2010", "name": name, "level_text": r.get("Level"),
                "ownership": (r.get("Status") or "").strip().lower() or None,
                "sponsor": r.get("Sponsor"), "lat": lat, "lon": lon,
                "province": (r.get("PROVINCE") or "").strip().title() or None,
                "district": (r.get("DISTRICT") or "").strip().title() or None,
                "division": (r.get("DIVISION") or "").strip().title() or None,
                "location": (r.get("LOCATION") or "").strip().title() or None,
                "sublocation": (r.get("SUBLOCATIO") or "").strip().title() or None,
                "classrooms": _num(r.get("# Classrooms")),
            }


def _pick(props, *names):
    low = {k.lower(): v for k, v in props.items()}
    for n in names:
        v = low.get(n.lower())
        if v not in (None, ""):
            return v
    return None


def read_2017():
    """The World Bank copy; its column names are matched loosely."""
    path = config.CACHE / config.WB_SCHOOLS_FILE
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except ValueError:
        log(f"  {path.name} isn't valid GeoJSON; skipping it (was it saved from the browser as a web page?)")
        return
    for f in data.get("features", []):
        p, g = f.get("properties") or {}, f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        lon, lat = g["coordinates"][:2]
        if abs(lat) > 90:  # projected (UTM 37S) rather than degrees
            lon, lat = _utm37s_to_lonlat(lon, lat)
        name = str(_pick(p, "SCHOOL_NAM", "School_Name", "SchoolName", "NAME", "Name") or "").strip()
        if not name:
            continue
        level_text = _pick(p, "LEVEL", "Level", "LEVEL_", "SchoolLeve", "Category") or ""
        yield {
            "key": _key("moe2017", name, level_text, round(lat, 5), round(lon, 5)),
            "source": "moe2017", "name": name, "level_text": str(level_text),
            "ownership": str(_pick(p, "STATUS", "Status", "Ownership", "OWNERSHIP") or "").strip().lower() or None,
            "sponsor": _pick(p, "SPONSOR", "Sponsor"), "lat": lat, "lon": lon,
            "province": str(_pick(p, "PROVINCE", "Province") or "").title() or None,
            "district": str(_pick(p, "DISTRICT", "District", "SUB_COUNTY", "SubCounty") or "").title() or None,
            "division": str(_pick(p, "DIVISION", "Division", "ZONE", "Zone") or "").title() or None,
            "location": str(_pick(p, "LOCATION", "Location") or "").title() or None,
            "sublocation": str(_pick(p, "SUBLOCATIO", "SUBLOCATION", "Sub_Locati") or "").title() or None,
            "classrooms": _num(_pick(p, "CLASSROOMS", "# Classrooms", "Classrooms")),
            "students": _num_big(_pick(p, "TOTAL_ENRO", "Enrollment", "ENROLMENT", "Total_Enrolment", "Pupils")),
            "teachers": _num_big(_pick(p, "TEACHERS", "Teachers", "TOTAL_TEAC", "TSC_Teache")),
        }


def _num_big(v):
    try:
        n = int(float(str(v).strip()))
        return n if 0 < n < 20000 else None
    except (TypeError, ValueError):
        return None


def _utm37s_to_lonlat(e, n):
    """Inverse transverse Mercator for UTM zone 37 south (WGS84)."""
    a, f, k0 = 6378137.0, 1 / 298.257223563, 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    x, y = e - 500000.0, n - 10000000.0
    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32)
            * math.sin(4 * mu) + (151 * e1 ** 3 / 96) * math.sin(6 * mu))
    n1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    t1 = math.tan(phi1) ** 2
    c1 = ep2 * math.cos(phi1) ** 2
    r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
                                              + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2)
                                              * d ** 6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2)
           * d ** 5 / 120) / math.cos(phi1)
    return 39 + math.degrees(lon), math.degrees(lat)


def _similar(a, b):
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = a.split(), b.split()
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    # "KIMALA" vs "ST PATRICK KIMALA": the shorter name is all inside the longer one
    return len("".join(short)) >= 5 and all(t in long_ for t in short)


def group_rows(rows):
    """Fold teaching units at one site into schools. Returns a list of groups (lists of rows)."""
    grid = {}
    groups = []
    for r in rows:
        r["mask"] = levels.moe_level(r["level_text"], r["name"])
        if levels.special_from_name(r["name"]) and not r["mask"]:
            r["mask"] = levels.PRIMARY
        r["base"] = levels.base_name(r["name"])
        tier = _tier(r["mask"])
        cx, cy = math.floor(r["lon"] / NEAR_DEG), math.floor(r["lat"] / NEAR_DEG)
        found = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for gi in grid.get((cx + dx, cy + dy), ()):
                    g = groups[gi]
                    if g["tier"] != tier:
                        continue
                    same_spot = abs(g["lat"] - r["lat"]) < 0.0003 and abs(g["lon"] - r["lon"]) < 0.0003
                    if not (_similar(g["base"], r["base"]) or
                            osm.name_score(levels.tokens(g["base"]), levels.tokens(r["base"])) >= (0.6 if same_spot else 0.75)):
                        continue
                    if abs(g["lat"] - r["lat"]) <= NEAR_DEG and abs(g["lon"] - r["lon"]) <= NEAR_DEG:
                        # Two distinct units of the same kind (two primaries) are different schools,
                        # unless one of them is the same row from another edition of the list.
                        same_level_twice = any(x["mask"] & r["mask"] & ~levels.ECDE and x["source"] == r["source"]
                                               and not levels.special_from_name(x["name"] + " " + r["name"])
                                               for x in g["rows"])
                        if not same_level_twice:
                            found = gi
                            break
                if found is not None:
                    break
            if found is not None:
                break
        if found is None:
            groups.append({"tier": tier, "base": r["base"], "lat": r["lat"], "lon": r["lon"], "rows": [r]})
            grid.setdefault((cx, cy), []).append(len(groups) - 1)
        else:
            g = groups[found]
            g["rows"].append(r)
            if len(r["base"]) > len(g["base"]):
                g["base"] = r["base"]
    return [g["rows"] for g in groups]


NAME_PRIORITY = [levels.SENIOR, levels.UNIVERSITY, levels.TTC, levels.TVET, levels.PRIMARY, levels.JUNIOR,
                 levels.NONFORMAL, levels.ECDE, levels.ADULT, 0]


def school_from_group(rows, loc):
    rows = sorted(rows, key=lambda r: (NAME_PRIORITY.index(next((b for b in NAME_PRIORITY if r["mask"] & b), 0)),
                                       r["source"] != "moe2017"))
    head = rows[0]
    mask = 0
    for r in rows:
        mask |= r["mask"]
    names = " ".join(r["name"] for r in rows)
    ownership = next((r["ownership"] for r in rows if r["ownership"] in ("public", "private")), None)
    sponsor = next((levels.sponsor_key(r["sponsor"]) for r in rows if levels.sponsor_key(r["sponsor"])), None)
    faith = levels.faith_from_name(names)
    if not faith and sponsor == "religious":
        faith = "Religious (unspecified)"
    lat = sum(r["lat"] for r in rows) / len(rows)
    lon = sum(r["lon"] for r in rows) / len(rows)
    where = loc.locate(lon, lat)
    classrooms = [r["classrooms"] for r in rows if r.get("classrooms")]
    ts = db.now()
    return {
        "name": levels.display_name(head["name"]), "levels": mask,
        "ownership": ownership, "sponsor": sponsor, "faith": faith,
        "gender": levels.gender_from_name(names), "boarding": levels.boarding_from_name(names),
        "special_needs": max(levels.special_from_name(r["name"]) for r in rows),
        "county_code": where["county_code"], "county": where["county"],
        "subcounty_code": where["subcounty_code"], "subcounty": where["subcounty"],
        "pop_density": round(where["density"]) if where["density"] is not None else None,
        "setting": areas.setting(where["density"]),
        "province": head["province"], "district": head["district"], "division": head["division"],
        "location": head["location"], "sublocation": head["sublocation"],
        "lat": round(lat, 6), "lon": round(lon, 6),
        "classrooms": sum(classrooms) if classrooms else None,
        "students": next((r.get("students") for r in rows if r.get("students")), None),
        "teachers": next((r.get("teachers") for r in rows if r.get("teachers")), None),
        "moe_keys": json.dumps(sorted(r["key"] for r in rows)),
        "sources": json.dumps(sorted({r["source"] for r in rows})),
        "extra": json.dumps({"moe_units": [{"name": levels.display_name(r["name"]), "level": r["level_text"],
                                            "edition": r["source"][3:]} for r in rows]}),
        "created_at": ts, "updated_at": ts,
    }


def ingest(conn):
    seen = set()
    for r in conn.execute("SELECT moe_keys FROM schools WHERE moe_keys != '[]'"):
        seen.update(json.loads(r["moe_keys"]))
    rows = [r for r in list(read_2010()) + list(read_2017() or []) if r["key"] not in seen]
    have_2017 = any(r["source"] == "moe2017" for r in rows)
    if not have_2017 and not (config.CACHE / config.WB_SCHOOLS_FILE).exists():
        log(f"  (optional) the 2017 edition isn't in data/cache/{config.WB_SCHOOLS_FILE}; using the 2010 list")
    if not rows:
        log("  every Ministry row is already in the directory")
        return {"new_rows": 0, "new_schools": 0}
    loc = areas.locator()
    kept = [r for r in rows if loc.in_kenya(r["lon"], r["lat"])]
    groups = group_rows(kept)
    log(f"  {len(kept):,} Ministry rows fold into {len(groups):,} schools")
    cols = None
    batch = []
    for g in groups:
        s = school_from_group(g, loc)
        cols = cols or list(s)
        batch.append(tuple(s[c] for c in cols))
    conn.executemany(f"INSERT INTO schools({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", batch)
    levels.apply_all_grades(conn)
    conn.commit()
    return {"rows": len(kept), "outside_kenya": len(rows) - len(kept), "new_schools": len(groups),
            "edition_2017": have_2017}

