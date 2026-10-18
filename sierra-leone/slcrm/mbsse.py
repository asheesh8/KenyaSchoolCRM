"""The Ministry's published school lists (MBSSE fee-subsidy payment schedules, 2019/20).

mbsse.gov.sl publishes one page per district and level (pre-primary, primary, junior and
senior secondary) listing every government and government-assisted school paid the
tuition subsidy: EMIS code, name, region, district, chiefdom, address and headcount.
Together they cover most of the country's ~13,000 approved schools, without contacts.
Run on your own computer: it needs open internet access. The research dataset already
holds the rows the research workers transcribed; this reads the pages directly and is
more accurate.
"""

import json
import re
from html.parser import HTMLParser

from . import db, levels
from .net import log, request

BASE = "https://mbsse.gov.sl/"
PAGES = {"pre_primary": ["pre-primary"] + [f"pre-primary-{i}" for i in range(2, 18)],
         "primary": ["primary"] + [f"primary-{i}" for i in range(2, 18)],
         "junior_secondary": ["jss"] + [f"jss-{i}" for i in range(2, 18)],
         "senior_secondary": ["sss"] + [f"sss-{i}" for i in range(2, 18)]}


class _Tables(HTMLParser):
    """Collects every table row as a list of cell texts."""

    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


COLS = {"emis": r"emis", "name": r"name", "district": r"district", "chiefdom": r"chiefdom",
        "address": r"address|town|location", "headcount": r"head ?count|enrol"}


def parse(html, page_district=None):
    """Rows of a schedule page -> dicts. Header rows may repeat mid-table; each resets the column map."""
    p = _Tables()
    p.feed(html)
    out, cols = [], None
    for row in p.rows:
        low = [c.lower() for c in row]
        if any("emis" in c for c in low) and any("name" in c for c in low):
            cols = {}
            for key, pat in COLS.items():
                for i, c in enumerate(low):
                    if re.search(pat, c) and key not in cols:
                        cols[key] = i
            continue
        if not cols or "name" not in cols or len(row) <= cols["name"]:
            continue
        get = lambda k: row[cols[k]].strip() if k in cols and cols[k] < len(row) else ""  # noqa: E731
        name, emis = get("name"), re.sub(r"\D", "", get("emis"))
        if not name or not emis:
            continue
        district = levels.canonical_district(re.sub(r"(?i)^(east|west|north|south|north west|western)\s+", "",
                                                    get("district"))) or page_district
        hc = re.sub(r"\D", "", get("headcount"))
        out.append({"emis": emis, "name": name, "district": district, "chiefdom": get("chiefdom") or None,
                    "town": get("address") or None, "headcount": int(hc) if hc else None})
    return out


def page_district(html):
    m = re.search(r"SCHOOLS IN ([A-Z ]+?) DISTRICT", html.upper())
    return levels.canonical_district(m.group(1).title()) if m else None


def ingest(conn, only=None):
    t = db.now()
    stats = {"pages": 0, "rows": 0, "added": 0, "matched": 0, "failed_pages": 0}
    for level, slugs in PAGES.items():
        if only and level not in only:
            continue
        for slug in slugs:
            url = BASE + slug
            try:
                html = request(url, timeout=60).decode("utf-8", "replace")
            except Exception as e:
                stats["failed_pages"] += 1
                log(f"  {url}: {e}")
                continue
            stats["pages"] += 1
            rows = parse(html, page_district(html))
            for r in rows:
                stats["rows"] += 1
                mk = levels.merge_key(r["name"])
                cand = conn.execute("SELECT * FROM schools WHERE emis_code=? AND district IS ?", (r["emis"], r["district"])) \
                    .fetchall()
                row = next((c for c in cand if levels.similar(c["name"], r["name"]) >= .6), None)
                if not row:
                    for c in conn.execute("SELECT * FROM schools WHERE norm=? AND district IS ?",
                                          (levels.norm_name(r["name"]), r["district"])).fetchall():
                        if levels.merge_key(c["name"]) == mk and \
                                levels.place_key(c["town"], c["chiefdom"]) == levels.place_key(r["town"], r["chiefdom"]):
                            row = c
                            break
                if row:
                    conn.execute("UPDATE schools SET emis_code=COALESCE(emis_code, ?), levels=levels|?, "
                                 "chiefdom=COALESCE(chiefdom, ?), town=COALESCE(town, ?), "
                                 "students=COALESCE(?, students), sources=?, updated_at=? WHERE id=?",
                                 (r["emis"], levels.BIT[level], r["chiefdom"], r["town"], r["headcount"],
                                  db.add_sources(row["sources"], url), t, row["id"]))
                    stats["matched"] += 1
                else:
                    faith = levels.faith_from_name(r["name"])
                    conn.execute(
                        "INSERT INTO schools(name, norm, kind, levels, ownership, denomination, district, province, "
                        "chiefdom, town, emis_code, students, sources, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r["name"], levels.norm_name(r["name"]), "school", levels.BIT[level],
                         "mission" if faith else "government_assisted", faith, r["district"],
                         levels.province(r["district"]), r["chiefdom"], r["town"], r["emis"], r["headcount"],
                         json.dumps([url]), t, t))
                    stats["added"] += 1
            conn.commit()
    return stats
