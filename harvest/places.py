"""Optional, paid: Google Places phone numbers, websites and open/closed status.

Needs GOOGLE_PLACES_API_KEY. Each lookup is one Text Search (New) request with
contact fields, billed at Google's Enterprise rate (roughly $35 per 1,000 as of
2025, with a monthly free allowance). Check current pricing before a big run,
and start with --limit.
"""

import json

from . import config, db, extract, levels, osm
from .net import log, request

URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ("places.id,places.displayName,places.location,places.formattedAddress,places.nationalPhoneNumber,"
          "places.internationalPhoneNumber,places.websiteUri,places.businessStatus")


def lookup(row):
    body = {"textQuery": f"{row['name']}, {row['county'] or ''}, Kenya", "regionCode": "KE", "maxResultCount": 5,
            "locationBias": {"circle": {"center": {"latitude": row["lat"], "longitude": row["lon"]},
                                        "radius": 5000.0}}}
    data = json.loads(request(URL, data=json.dumps(body), method="POST", timeout=30, headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": config.GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": FIELDS}))
    toks = levels.tokens(row["name"])
    best = None
    for p in data.get("places", []):
        loc = p.get("location") or {}
        d = osm._km(row["lat"], row["lon"], loc.get("latitude", 0), loc.get("longitude", 0))
        s = osm.name_score(toks, levels.tokens((p.get("displayName") or {}).get("text", "")))
        if s >= 0.75 and d <= 5 and (best is None or s - d / 20 > best[0]):
            best = (s - d / 20, p)
    return best[1] if best else None


def run(conn, counties=None, limit=None, stale_days=180, levels=None):
    if not config.GOOGLE_PLACES_API_KEY:
        raise SystemExit("Set GOOGLE_PLACES_API_KEY to use Google Places (a paid Google Cloud API).")
    where = ["(s.phone IS NULL OR s.website IS NULL)", "s.lat IS NOT NULL",
             "(s.places_at IS NULL OR s.places_at < ?)"]
    params = [db.now() - stale_days * 86400]
    if levels:
        from . import levels as lv
        mask = 0
        for k in levels.split(","):
            mask |= lv.BY_KEY[k.strip()]
        where.append(f"s.levels & {mask}")
    if counties:
        where.append(f"s.county_code IN ({','.join('?' * len(counties))})")
        params += counties
    q = (f"SELECT id, name, county, lat, lon FROM schools s WHERE {' AND '.join(where)} "
         f"ORDER BY (s.levels & 8) DESC, s.ownership='private' DESC LIMIT {int(limit or 200)}")
    rows = conn.execute(q, params).fetchall()
    log(f"  looking up {len(rows):,} schools on Google Places")
    found = 0
    for i, r in enumerate(rows, 1):
        ts = db.now()
        try:
            p = lookup(r)
        except Exception as e:
            log(f"  Places error: {str(e)[:120]}")
            break
        fields = {"places_at": ts}
        if p:
            found += 1
            fields["places_id"] = p.get("id")
            if p.get("businessStatus") and p["businessStatus"] != "OPERATIONAL":
                fields["business_status"] = p["businessStatus"]
            src = f"https://www.google.com/maps/place/?q=place_id:{p.get('id')}"
            ph = extract.normalize_phone(p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber"))
            if ph:
                db.upsert_contact(conn, r["id"], "phone", ph, "places", source_url=src, score=2, ts=ts)
            for kind, value, label in osm.url_contacts(p.get("websiteUri")):
                db.upsert_contact(conn, r["id"], kind, value, "places", source_url=src, score=2, ts=ts)
        conn.execute(f"UPDATE schools SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                     (*fields.values(), r["id"]))
        db.refresh_primary(conn, r["id"])
        if i % 25 == 0:
            conn.commit()
            log(f"  {i:,}/{len(rows):,}, {found:,} found")
    conn.commit()
    return {"looked_up": len(rows), "found": found}
