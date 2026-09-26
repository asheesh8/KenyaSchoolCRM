"""Counties and constituencies, with populations, and point lookups into them.

- Boundaries: OCHA / IEBC administrative boundaries (47 counties, 290
  constituencies), published on HDX as cod-ab-ken.
- County population: 2019 Kenya Population and Housing Census (KNBS), via HDX
  cod-ps-ken, including the school-age (5-19) count.
- Constituency population and each school's local density: WorldPop 2020
  (UN-adjusted, 1 km grid), because the census tables use sub-county lines that
  don't match constituency boundaries.
"""

import csv
import io
import json
import math
import re
import zipfile

from . import config, db, geo, net
from .net import log

WORLDPOP_URL = ("https://data.worldpop.org/GIS/Population_Density/Global_2000_2020_1km_UNadj/2020/KEN/"
                "ken_pd_2020_1km_UNadj_ASCII_XYZ.zip")
CELL = 1 / 120  # WorldPop 30 arc-second grid

# Population density thresholds (people per km2) for a school's setting, after
# the UN Degree of Urbanisation: 1,500+ is an urban centre, 300+ an urban cluster.
URBAN, PERI_URBAN = 1500, 300


def _boundaries():
    path = net.cached_download(config.ADMIN_BOUNDARIES_URL, "ken_admin_boundaries.geojson.zip", max_age_days=365)
    z = zipfile.ZipFile(path)
    names = z.namelist()
    pick = lambda suffix: json.loads(z.read(next(n for n in names if n.endswith(suffix))))  # noqa: E731
    return pick("admin0.geojson"), pick("admin1.geojson"), pick("admin2.geojson")


def _xlsx_rows(path, sheet_name):
    """Just enough of the .xlsx format to read one sheet of numbers and strings."""
    z = zipfile.ZipFile(path)
    shared = [re.sub(r"<[^>]+>", "", s) for s in
              re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S)]
    book = z.read("xl/workbook.xml").decode()
    sheets = re.findall(r'<sheet [^>]*name="([^"]+)"[^>]*r:id="rId(\d+)"', book)
    sheet_no = next((rid for name, rid in sheets if name == sheet_name), None)
    xml = z.read(f"xl/worksheets/sheet{sheet_no}.xml").decode()
    rows = []
    for r in re.findall(r"<row [^>]*>(.*?)</row>", xml, re.S):
        d = {}
        for col, attrs, v in re.findall(r'<c r="([A-Z]+)\d+"([^>]*)>(?:<f>.*?</f>)?<v>([^<]*)</v>', r):
            d[col] = shared[int(v)] if 't="s"' in attrs else v
        rows.append(d)
    header = rows[0]
    return [{header[k]: v for k, v in r.items() if k in header} for r in rows[1:]]


def _county_population():
    path = net.cached_download(config.ADMIN_POP_URL, "ken_admpop_2019.xlsx", max_age_days=365)
    out = {}
    for r in _xlsx_rows(path, "ken_admpop_ADM1_2019"):
        code = r.get("ADM1_PCODE")
        if not code:
            continue
        school_age = sum(int(float(r.get(f"{s}_{a}", 0) or 0)) for s in ("F", "M") for a in ("05_09", "10_14", "15_19"))
        out[code] = (int(float(r["T_TL"])), school_age)
    return out


class DensityGrid:
    """WorldPop people-per-km2, looked up by coordinate."""

    def __init__(self):
        path = net.cached_download(WORLDPOP_URL, "ken_pd_2020_1km_UNadj_ASCII_XYZ.zip", max_age_days=3650)
        z = zipfile.ZipFile(path)
        self.cells = {}
        self.off = None
        with z.open(z.namelist()[0]) as f:
            reader = csv.reader(io.TextIOWrapper(f))
            next(reader)
            for x, y, v in reader:
                x, y = float(x) / CELL, float(y) / CELL
                if self.off is None:  # the grid's cell edges don't sit on whole multiples of CELL
                    self.off = ((x - 0.5) % 1, (y - 0.5) % 1)
                self.cells[(math.floor(x - self.off[0]), math.floor(y - self.off[1]))] = float(v)

    def density(self, lon, lat):
        return self.cells.get((math.floor(lon / CELL - self.off[0]), math.floor(lat / CELL - self.off[1])))

    def items(self):
        for (ix, iy), v in self.cells.items():
            lon, lat = (ix + self.off[0] + 0.5) * CELL, (iy + self.off[1] + 0.5) * CELL
            area = (CELL * 111.32) ** 2 * math.cos(math.radians(lat))
            yield lon, lat, v * area


def setting(density):
    if density is None:
        return None
    return "urban" if density >= URBAN else "peri_urban" if density >= PERI_URBAN else "rural"


def simplify(geometry, tolerance=0.004):
    """Douglas-Peucker on each ring; small enough to draw every county in a browser."""
    def dp(points):
        if len(points) < 4:
            return points
        keep = [False] * len(points)
        keep[0] = keep[-1] = True
        stack = [(0, len(points) - 1)]
        while stack:
            a, b = stack.pop()
            ax, ay = points[a][:2]
            bx, by = points[b][:2]
            dx, dy = bx - ax, by - ay
            norm = math.hypot(dx, dy)
            best, idx = 0, None
            for i in range(a + 1, b):
                px, py = points[i][:2]
                # a closed ring starts and ends on the same point: measure from that point instead
                d = abs(dy * px - dx * py + bx * ay - by * ax) / norm if norm else math.hypot(px - ax, py - ay)
                if d > best:
                    best, idx = d, i
            if idx is not None and best > tolerance:
                keep[idx] = True
                stack += [(a, idx), (idx, b)]
        out = [[round(p[0], 4), round(p[1], 4)] for p, k in zip(points, keep) if k]
        return out if len(out) >= 4 else []

    def poly(rings):
        rings = [dp(r) for r in rings]
        return [r for r in rings if r]

    if geometry["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": poly(geometry["coordinates"])}
    polys = [poly(p) for p in geometry["coordinates"]]
    return {"type": "MultiPolygon", "coordinates": [p for p in polys if p]}


def refresh_shapes(conn):
    """Re-store the simplified outlines only (no population work)."""
    admin0, admin1, admin2 = _boundaries()
    for f, tol in [(f, 0.004) for f in admin1["features"]] + [(f, 0.002) for f in admin2["features"]]:
        p = f["properties"]
        code = p.get("adm2_pcode") or p["adm1_pcode"]
        conn.execute("UPDATE areas SET geometry=? WHERE code=?", (json.dumps(simplify(f["geometry"], tol)), code))
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('kenya_outline', ?)",
                 (json.dumps(simplify(admin0["features"][0]["geometry"], 0.01)),))
    conn.commit()


def build(conn):
    admin0, admin1, admin2 = _boundaries()
    census = _county_population()
    log("  reading the WorldPop density grid")
    grid = DensityGrid()
    idx2 = AreaIndex([(f["properties"]["adm2_pcode"], f["geometry"]) for f in admin2["features"]])
    log("  summing constituency populations")
    const_pop = {}
    for lon, lat, people in grid.items():
        code = idx2.locate(lon, lat)
        if code:
            const_pop[code] = const_pop.get(code, 0) + people
    rows = []
    for f in admin1["features"]:
        p, g = f["properties"], f["geometry"]
        pop, school_age = census.get(p["adm1_pcode"], (None, None))
        rows.append((p["adm1_pcode"], "county", p["adm1_name"], None, pop, school_age, p.get("area_sqkm"),
                     p.get("center_lat"), p.get("center_lon"), json.dumps(geo.bbox(g)), json.dumps(simplify(g))))
    county_share = {code: (sa / pop) for code, (pop, sa) in census.items() if pop}
    for f in admin2["features"]:
        p, g = f["properties"], f["geometry"]
        pop = round(const_pop.get(p["adm2_pcode"], 0))
        rows.append((p["adm2_pcode"], "subcounty", p["adm2_name"], p["adm1_pcode"], pop,
                     round(pop * county_share.get(p["adm1_pcode"], 0.4)), p.get("area_sqkm"),
                     p.get("center_lat"), p.get("center_lon"), json.dumps(geo.bbox(g)), json.dumps(simplify(g, 0.002))))
    conn.execute("DELETE FROM areas")
    conn.executemany("INSERT INTO areas(code, kind, name, county_code, population, school_age, area_sqkm, lat, lon, "
                     "bbox, geometry) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('kenya_outline', ?)",
                 (json.dumps(simplify(admin0["features"][0]["geometry"], 0.01)),))
    conn.commit()
    return {"counties": len(admin1["features"]), "constituencies": len(admin2["features"]),
            "population_2019": sum(p for p, _ in census.values())}


class AreaIndex:
    """Point-in-polygon lookup with a coarse grid so 100k lookups stay quick."""

    STEP = 0.25

    def __init__(self, items):
        self.items = []
        self.grid = {}
        for code, g in items:
            b = geo.bbox(g)
            if not b:
                continue
            i = len(self.items)
            self.items.append((code, g, b))
            for gx in range(math.floor(b[0] / self.STEP), math.floor(b[2] / self.STEP) + 1):
                for gy in range(math.floor(b[1] / self.STEP), math.floor(b[3] / self.STEP) + 1):
                    self.grid.setdefault((gx, gy), []).append(i)

    def locate(self, lon, lat):
        for i in self.grid.get((math.floor(lon / self.STEP), math.floor(lat / self.STEP)), ()):
            code, g, b = self.items[i]
            if b[0] <= lon <= b[2] and b[1] <= lat <= b[3] and geo.contains(g, lon, lat):
                return code
        return None

    def nearest(self, lon, lat, max_deg=0.05):
        """For points just off the coast or a border: the area whose edge is closest."""
        best = None
        for code, g, b in self.items:
            if b[0] - max_deg <= lon <= b[2] + max_deg and b[1] - max_deg <= lat <= b[3] + max_deg:
                for poly in geo._rings(g):
                    for x, y in poly[0][::3]:
                        d = (x - lon) ** 2 + (y - lat) ** 2
                        if best is None or d < best[0]:
                            best = (d, code)
        return best[1] if best and best[0] <= max_deg ** 2 else None


_locator = None


class Locator:
    """Answers: which county and constituency is this point in, and how dense is it?"""

    def __init__(self):
        admin0, admin1, admin2 = _boundaries()
        self.kenya = admin0["features"][0]["geometry"]
        self.counties = AreaIndex([(f["properties"]["adm1_pcode"], f["geometry"]) for f in admin1["features"]])
        self.consts = AreaIndex([(f["properties"]["adm2_pcode"], f["geometry"]) for f in admin2["features"]])
        self.names = {f["properties"]["adm1_pcode"]: f["properties"]["adm1_name"] for f in admin1["features"]}
        self.names.update({f["properties"]["adm2_pcode"]: f["properties"]["adm2_name"] for f in admin2["features"]})
        self.grid = DensityGrid()

    def locate(self, lon, lat):
        county = self.counties.locate(lon, lat) or self.counties.nearest(lon, lat)
        const = self.consts.locate(lon, lat) or self.consts.nearest(lon, lat)
        if const and county and not const.startswith(county):
            const = None
        return {"county_code": county, "county": self.names.get(county), "subcounty_code": const,
                "subcounty": self.names.get(const), "density": self.grid.density(lon, lat)}

    def in_kenya(self, lon, lat):
        return geo.contains(self.kenya, lon, lat) or bool(self.counties.nearest(lon, lat, 0.02))


def locator():
    global _locator
    if _locator is None:
        log("  loading boundaries and density grid")
        _locator = Locator()
    return _locator


def assign(conn, only_missing=True):
    """Put every school in its county and constituency, and record local density."""
    loc = locator()
    q = "SELECT id, lat, lon FROM schools WHERE lat IS NOT NULL"
    if only_missing:
        q += " AND county_code IS NULL"
    n = 0
    for r in conn.execute(q).fetchall():
        a = loc.locate(r["lon"], r["lat"])
        conn.execute("UPDATE schools SET county_code=?, county=?, subcounty_code=?, subcounty=?, pop_density=?, "
                     "setting=? WHERE id=?", (a["county_code"], a["county"], a["subcounty_code"], a["subcounty"],
                                              round(a["density"]) if a["density"] is not None else None,
                                              setting(a["density"]), r["id"]))
        n += 1
    conn.commit()
    return n
