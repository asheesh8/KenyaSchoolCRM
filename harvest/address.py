"""A readable address for every school.

Kenyan schools rarely have street addresses, so the address is built the way
people give directions: nearest named place (from OpenStreetMap), location,
constituency, county, e.g. "Near Kimala village, Kimala Location, Mumias East,
Kakamega County". The P.O. Box, where known, stays in its own field.
"""

import json
import math

from . import config, db
from .net import log

RANK = {"city": 6, "town": 5, "suburb": 4, "quarter": 3, "neighbourhood": 3, "village": 2, "hamlet": 1}
REACH_KM = {"city": 15, "town": 6, "suburb": 3, "quarter": 2, "neighbourhood": 2, "village": 4, "hamlet": 2}


def run(conn):
    places = []
    grid = {}
    for e in json.loads((config.CACHE / "osm_places.json").read_text())["elements"]:
        name = (e.get("tags") or {}).get("name")
        if not name or "lat" not in e:
            continue
        p = (e["lat"], e["lon"], name, e["tags"]["place"])
        grid.setdefault((math.floor(p[0] * 10), math.floor(p[1] * 10)), []).append(p)
    n = 0
    for r in conn.execute("SELECT id, lat, lon, town, location, subcounty, county, extra FROM schools").fetchall():
        near = None
        if r["lat"] is not None:
            gy, gx = math.floor(r["lat"] * 10), math.floor(r["lon"] * 10)
            best = None
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    for lat, lon, name, kind in grid.get((gy + dy, gx + dx), ()):
                        km = math.hypot((lat - r["lat"]) * 111, (lon - r["lon"]) * 111 * math.cos(math.radians(lat)))
                        if km > REACH_KM[kind]:
                            continue
                        score = km - RANK[kind] * 0.3
                        if best is None or score < best[0]:
                            best = (score, name, kind)
            if best:
                near = f"Near {best[1]}" + (f" {best[2]}" if best[2] in ("village", "town") and best[2] not in best[1].lower() else "")
        extra = json.loads(r["extra"] or "{}")
        parts = [near or (r["town"] and f"{r['town']}") or extra.get("physical_location")]
        if r["location"] and (not near or r["location"].lower() not in near.lower()):
            parts.append(f"{r['location']} Location")
        if r["subcounty"]:
            parts.append(r["subcounty"])
        if r["county"]:
            parts.append(f"{r['county']} County")
        addr = ", ".join(p for p in parts if p)
        conn.execute("UPDATE schools SET address=? WHERE id=?", (addr or None, r["id"]))
        n += 1
    conn.commit()
    return {"schools": n, "with_address": conn.execute("SELECT COUNT(*) FROM schools WHERE address IS NOT NULL").fetchone()[0]}
