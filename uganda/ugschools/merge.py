"""Research files -> one clean dataset in the shared Africa CRM format.

`merge` folds the raw files (osm.jsonl as the base list, plus one JSONL per research worker,
see dataset/SCHEMA.md) into uganda-schools.jsonl, schools.csv, contacts.csv and summary.json.
Institutions are deduped by name within a district (and sub-county when both sides have one),
or by EMIS/UNEB code. The CRM loads the result with `python3 -m africacrm load --country UG`.
"""

import csv
import glob
import hashlib
import json
import os
from collections import Counter

from . import config, levels

VALID_LEVELS = {k for k, *_ in levels.LEVELS}
LEGACY_LEVELS = {"junior_secondary": "lower_secondary", "senior_secondary": "upper_secondary"}
VALID_KIND = {"school", "office", "secretariat", "association", "ngo"}
VALID_OWNERSHIP = {"government", "government_assisted", "private", "community", "mission", "ngo"}
VALID_CONF = {"high", "medium", "low"}
CONF_RANK = {"high": 3, "medium": 2, "low": 1, None: 0}
GENERIC_DOMAINS = {"gmail.com", "yahoo.com", "yahoo.co.uk", "hotmail.com", "outlook.com", "live.com", "icloud.com",
                   "aol.com", "ymail.com", "googlemail.com", "hotmail.co.uk", "mail.com", "protonmail.com"}


def _read_raw(raw_dir):
    out = []
    for path in sorted(glob.glob(os.path.join(str(raw_dir), "*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and isinstance(rec.get("name"), str) and rec["name"].strip():
                    rec.setdefault("worker", os.path.basename(path).rsplit(".", 1)[0])
                    out.append(rec)
    return out


def _url(u):
    u = (u or "").strip() if isinstance(u, str) else ""
    return u if u.startswith(("http://", "https://")) else None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def normalize(rec):
    """One raw record -> the dataset's shape, with everything unverifiable dropped."""
    name = " ".join(rec["name"].split())
    sources = [u for u in (_url(s) for s in rec.get("sources") or []) if u]
    lv = []
    for k in rec.get("levels") or []:
        k = LEGACY_LEVELS.get(k, k)
        if k in VALID_LEVELS and k not in lv:
            lv.append(k)
    lv = lv or levels.levels_from_name(name)
    kind = rec.get("kind") if rec.get("kind") in VALID_KIND else "school"
    if kind != "school" and "admin" not in lv:
        lv.append("admin")
    district = levels.canonical_district(rec.get("district")) or levels.district_from_text(
        rec.get("town"), rec.get("address"), rec.get("area"), name)
    emails, seen = [], set()
    for e in rec.get("emails") or []:
        if isinstance(e, str):
            e = {"email": e}
        if not isinstance(e, dict):
            continue
        addr = levels.clean_email(e.get("email"))
        src = _url(e.get("source_url")) or (sources[0] if len(sources) == 1 else None)
        if not addr or not src or addr in seen:
            continue  # an address without the page it came from can't be checked, so it's left out
        seen.add(addr)
        emails.append({"email": addr, "source_url": src,
                       "confidence": e.get("confidence") if e.get("confidence") in VALID_CONF else "medium",
                       "seen": e.get("seen"), "person": None, "role": None})
    phones, pseen = [], set()
    for p in rec.get("phones") or []:
        if isinstance(p, str):
            p = {"phone": p}
        if not isinstance(p, dict):
            continue
        num = levels.clean_phone(p.get("phone"))
        if num and num not in pseen:
            pseen.add(num)
            phones.append({"phone": num, "source_url": _url(p.get("source_url")) or (sources[0] if sources else None)})
    officials = []
    for o in rec.get("officials") or []:
        if not isinstance(o, dict) or not isinstance(o.get("name"), str) or not o["name"].strip():
            continue
        src = _url(o.get("source_url")) or (sources[0] if len(sources) == 1 else None)
        off = {"name": " ".join(o["name"].split()), "role": (o.get("role") or "").strip() or None,
               "email": levels.clean_email(o.get("email")) if src else None,
               "phone": levels.clean_phone(o.get("phone")), "source_url": src}
        officials.append(off)
        if off["email"] and off["email"] not in seen:
            seen.add(off["email"])
            emails.append({"email": off["email"], "source_url": src, "confidence": "medium", "seen": None,
                           "person": off["name"], "role": off["role"]})
        elif off["email"]:
            for e in emails:
                if e["email"] == off["email"] and not e["person"]:
                    e["person"], e["role"] = off["name"], off["role"]
        if off["phone"] and off["phone"] not in pseen:
            pseen.add(off["phone"])
            phones.append({"phone": off["phone"], "source_url": src})
    sources += [e["source_url"] for e in emails] + [p["source_url"] for p in phones if p["source_url"]]
    own = rec.get("ownership") if rec.get("ownership") in VALID_OWNERSHIP else None
    denom = rec.get("denomination") or levels.faith_from_name(name)
    if not own and denom and kind == "secretariat":
        own = "mission"
    students = rec.get("students")
    return {
        "id": None, "country": config.COUNTRY, "name": name, "kind": kind,
        "levels": sorted(lv, key=levels.ORDER.get), "province": levels.region(district) or rec.get("region"),
        "district": district, "area": rec.get("area") or rec.get("subcounty") or None,
        "county": rec.get("county") or None, "town": rec.get("town") or None, "address": rec.get("address") or None,
        "ownership": own or "unknown", "denomination": denom, "website": _url(rec.get("website")),
        "emails": emails, "phones": phones, "officials": officials,
        "emis_code": str(rec["emis_code"]).strip() if rec.get("emis_code") else None,
        "lat": _num(rec.get("lat")), "lon": _num(rec.get("lon")),
        "students": int(students) if isinstance(students, (int, float)) and students > 0 else None,
        "sources": sorted(set(sources)), "notes": rec.get("notes") or None, "osm_id": rec.get("osm_id"),
        "workers": [rec.get("worker")] if rec.get("worker") else [],
    }


def _has_contacts(r):
    return bool(r["emails"] or r["phones"] or r["officials"])


def _fold(a, b):
    """Merge b into a (both normalized)."""
    for k in ("district", "province", "area", "county", "town", "address", "denomination", "website", "emis_code",
              "lat", "lon", "students", "osm_id"):
        if not a.get(k) and b.get(k):
            a[k] = b[k]
    if a.get("ownership") in (None, "unknown") and b.get("ownership") not in (None, "unknown"):
        a["ownership"] = b["ownership"]
    if a["kind"] == "school" and b["kind"] != "school":
        a["kind"] = b["kind"]
    # A researched name beats the map's spelling.
    if "osm" in a["workers"] and "osm" not in b["workers"]:
        a["name"] = b["name"]
    lv = set(a["levels"]) | set(b["levels"])
    if a.get("notes") and "level guessed" in a["notes"] and b["levels"]:
        lv = set(b["levels"])
        a["notes"] = a["notes"].replace("; level guessed (name gives none)", "")
    a["levels"] = sorted(lv, key=levels.ORDER.get)
    if b.get("notes") and b["notes"] != a.get("notes"):
        a["notes"] = "; ".join(x for x in (a.get("notes"), b["notes"]) if x)
    have = {e["email"]: e for e in a["emails"]}
    for e in b["emails"]:
        if e["email"] in have:
            cur = have[e["email"]]
            if CONF_RANK.get(e["confidence"], 0) > CONF_RANK.get(cur["confidence"], 0):
                cur["confidence"], cur["source_url"] = e["confidence"], e["source_url"]
            cur["person"] = cur["person"] or e["person"]
            cur["role"] = cur["role"] or e["role"]
        else:
            a["emails"].append(e)
    ph = {p["phone"] for p in a["phones"]}
    a["phones"] += [p for p in b["phones"] if p["phone"] not in ph]
    names = {(o["name"].lower(), (o["role"] or "").lower()) for o in a["officials"]}
    a["officials"] += [o for o in b["officials"] if (o["name"].lower(), (o["role"] or "").lower()) not in names]
    a["sources"] = sorted(set(a["sources"]) | set(b["sources"]))
    a["workers"] = sorted(set(a["workers"]) | set(b["workers"]))


_FAMILY = {"lower_secondary": "secondary", "upper_secondary": "secondary"}


def _levels_agree(a, b):
    fa = {_FAMILY.get(k, k) for k in a["levels"]}
    fb = {_FAMILY.get(k, k) for k in b["levels"]}
    return not fa or not fb or bool(fa & fb)


def _find(r, by_emis, by_key, by_name, by_norm):
    mk = levels.merge_key(r["name"])
    area = levels.place_key(r["area"], r["town"])
    if r["emis_code"]:
        hit = next((m for m in by_emis.get(r["emis_code"], []) if levels.similar(m["name"], r["name"]) >= .5), None)
        if hit:
            return hit
    if (mk, r["district"], area) in by_key and area:
        return by_key[(mk, r["district"], area)]
    cands = by_name.get((mk, r["district"]), [])
    if r["district"] is None:
        cands = by_name.get((mk, "*"), [])
    if len(cands) == 1 and (not area or not levels.place_key(cands[0]["area"], cands[0]["town"])
                            or levels.place_key(cands[0]["area"], cands[0]["town"]) == area):
        return cands[0]
    if len(cands) > 1 and area:
        same = [c for c in cands if levels.place_key(c["area"], c["town"]) == area]
        if len(same) == 1:
            return same[0]
    if not cands and r["district"] and _has_contacts(r):
        # Looser pass for researched records: the same name without level words, or nearly the same tokens,
        # and exactly one such institution in the district.
        loose = [c for c in by_norm.get((levels.norm_name(r["name"]), r["district"]), []) if _levels_agree(c, r)]
        if len(loose) == 1:
            return loose[0]
    return None


def merge(raw_dir=None, out_dir=None):
    raw_dir = raw_dir or config.RAW_DIR
    out_dir = out_dir or config.DATASET_DIR
    raw = _read_raw(raw_dir)
    # The map's entries first: they carry the sub-county, so a researched record can tell same-named schools apart.
    recs = sorted((normalize(r) for r in raw), key=lambda r: "osm" not in r["workers"])
    by_emis, by_key, by_name, by_norm, merged = {}, {}, {}, {}, []
    for r in recs:
        target = _find(r, by_emis, by_key, by_name, by_norm)
        if target is not None:
            _fold(target, r)
            r = target
        else:
            merged.append(r)
            mk = levels.merge_key(r["name"])
            by_name.setdefault((mk, r["district"]), []).append(r)
            by_name.setdefault((mk, "*"), []).append(r)
            by_norm.setdefault((levels.norm_name(r["name"]), r["district"]), []).append(r)
        area = levels.place_key(r["area"], r["town"])
        if area:
            by_key.setdefault((levels.merge_key(r["name"]), r["district"], area), r)
        if r["emis_code"]:
            by_emis.setdefault(r["emis_code"], []).append(r)
    # A personal-domain email found on two different institutions is ambiguous: keep it, but mark it low.
    owners = Counter(e["email"] for r in merged for e in r["emails"])
    ids = Counter()
    for r in merged:
        for e in r["emails"]:
            if owners[e["email"]] > 1 and e["email"].split("@")[-1] in GENERIC_DOMAINS:
                e["confidence"] = "low"
        base = r["osm_id"] or (f"{levels.merge_key(r['name'])}|{r['district']}|"
                               f"{levels.place_key(r['area'], r['town'])}|{r['emis_code']}")
        rid = hashlib.sha1(str(base).encode()).hexdigest()[:12]
        ids[rid] += 1
        r["id"] = rid if ids[rid] == 1 else f"{rid}-{ids[rid]}"
    merged.sort(key=lambda r: (r["province"] or "~", r["district"] or "~", levels.norm_name(r["name"])))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, config.DATASET_NAME), "w", encoding="utf-8") as f:
        for r in merged:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    _write_csvs(merged, out_dir)
    stats = summarize(merged)
    stats["raw_records"] = len(recs)
    stats["raw_by_worker"] = dict(Counter(r.get("worker") for r in raw))
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(stats, f, indent=2)
    return stats


def _best_email(r):
    return sorted(r["emails"], key=lambda e: (-CONF_RANK.get(e["confidence"], 0), e["person"] is not None))


def _write_csvs(merged, out_dir):
    with open(os.path.join(out_dir, "schools.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "kind", "levels", "district", "province", "area", "town", "ownership",
                    "denomination", "emis_code", "best_email", "email_confidence", "all_emails", "phones",
                    "whatsapp", "head_or_official", "website", "lat", "lon", "sources"])
        for r in merged:
            best = _best_email(r)
            head = next((f"{o['name']} ({o['role']})" if o["role"] else o["name"] for o in r["officials"]), "")
            mobile = next((p["phone"] for p in r["phones"] if levels.is_mobile(p["phone"])), "")
            w.writerow([r["id"], r["name"], r["kind"], ";".join(r["levels"]), r["district"] or "", r["province"] or "",
                        r["area"] or "", r["town"] or "", r["ownership"], r["denomination"] or "",
                        r["emis_code"] or "", best[0]["email"] if best else "", best[0]["confidence"] if best else "",
                        ";".join(e["email"] for e in r["emails"]), ";".join(p["phone"] for p in r["phones"]),
                        mobile, head, r["website"] or "", r["lat"] or "", r["lon"] or "", " ".join(r["sources"])])
    with open(os.path.join(out_dir, "contacts.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["institution_id", "institution", "district", "levels", "type", "value", "person", "role",
                    "confidence", "source_url"])
        for r in merged:
            base = [r["id"], r["name"], r["district"] or "", ";".join(r["levels"])]
            for e in r["emails"]:
                w.writerow(base + ["email", e["email"], e["person"] or "", e["role"] or "", e["confidence"],
                                   e["source_url"]])
            for p in r["phones"]:
                w.writerow(base + ["whatsapp" if levels.is_mobile(p["phone"]) else "phone", p["phone"], "", "", "",
                                   p["source_url"] or ""])
            for o in r["officials"]:
                w.writerow(base + ["official", o["name"], o["name"], o["role"] or "", "", o["source_url"] or ""])


def summarize(merged):
    emails = {e["email"] for r in merged for e in r["emails"]}
    by_level = Counter(k for r in merged for k in r["levels"])
    by_district = Counter(r["district"] or "Unknown" for r in merged)
    email_by_region = Counter(r["province"] or "Unknown" for r in merged if r["emails"])
    return {
        "country": config.COUNTRY,
        "institutions": len(merged),
        "with_email": sum(1 for r in merged if r["emails"]),
        "unique_emails": len(emails),
        "emails_by_confidence": dict(Counter(e["confidence"] for r in merged for e in r["emails"])),
        "with_phone": sum(1 for r in merged if r["phones"]),
        "with_mobile": sum(1 for r in merged if any(levels.is_mobile(p["phone"]) for p in r["phones"])),
        "unique_phones": len({p["phone"] for r in merged for p in r["phones"]}),
        "with_named_official": sum(1 for r in merged if r["officials"]),
        "with_any_contact": sum(1 for r in merged if _has_contacts(r)),
        "by_level": {k: by_level.get(k, 0) for k, *_ in levels.LEVELS},
        "by_kind": dict(Counter(r["kind"] for r in merged)),
        "by_region": dict(Counter(r["province"] or "Unknown" for r in merged)),
        "with_email_by_region": dict(email_by_region),
        "by_district": dict(sorted(by_district.items())),
        "by_ownership": dict(Counter(r["ownership"] for r in merged)),
    }
