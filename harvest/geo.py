"""Just enough geometry to answer "which qualifying city is this point inside?"."""

import json


def _rings(geometry):
    """Yield polygons as lists of rings (outer first) for Polygon/MultiPolygon."""
    t = geometry.get("type")
    if t == "Polygon":
        yield geometry["coordinates"]
    elif t == "MultiPolygon":
        yield from geometry["coordinates"]


def _in_ring(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi:
            inside = not inside
        j = i
    return inside


def contains(geometry, lon, lat):
    for poly in _rings(geometry):
        if not poly or not _in_ring(lon, lat, poly[0]):
            continue
        if any(_in_ring(lon, lat, hole) for hole in poly[1:]):
            continue
        return True
    return False


def bbox(geometry):
    xs, ys = [], []
    for poly in _rings(geometry):
        for x, y in poly[0]:
            xs.append(x)
            ys.append(y)
    return [min(xs), min(ys), max(xs), max(ys)] if xs else None


class CityIndex:
    """Point-in-polygon lookup across a set of cities (typically one state).

    When a point sits in more than one qualifying area (a village inside a
    New York town, a CDP inside a New Jersey township) the most specific wins:
    incorporated city, then CDP, then town.
    """

    PRIORITY = {"city": 0, "cdp": 1, "town": 2}

    def __init__(self, rows):
        self.items = []
        for r in rows:
            if not r["geometry"]:
                continue
            g = json.loads(r["geometry"])
            b = json.loads(r["bbox"]) if r["bbox"] else bbox(g)
            if b:
                self.items.append((b, g, r["id"], self.PRIORITY.get(r["kind"], 3)))

    def locate(self, lon, lat):
        best = None
        for b, g, cid, pri in self.items:
            if b[0] <= lon <= b[2] and b[1] <= lat <= b[3] and contains(g, lon, lat):
                if best is None or pri < best[1]:
                    best = (cid, pri)
        return best[0] if best else None

    def union_bbox(self):
        if not self.items:
            return None
        return [
            min(i[0][0] for i in self.items), min(i[0][1] for i in self.items),
            max(i[0][2] for i in self.items), max(i[0][3] for i in self.items),
        ]
