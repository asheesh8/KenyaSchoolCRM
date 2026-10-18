"""Research files -> one clean dataset -> the CRM database.

`merge` folds the raw research files (one JSONL per research worker, see
dataset/SCHEMA.md) into dataset/sierra-leone-schools.jsonl plus two spreadsheets,
deduping institutions by name and district, or by EMIS code. `load` puts that dataset
into the CRM, keeping any outreach history already there.
"""

import csv
import glob
import hashlib
import json
import os
from collections import Counter

from . import config, db, levels

VALID_LEVELS = {k for k, *_ in levels.LEVELS}
VALID_OWNERSHIP = {"government", "government_assisted", "private", "community", "mission", "ngo"}
VALID_CONF = {"high", "medium", "low"}
GENERIC_DOMAINS = {"gmail.com", "yahoo.com", "yahoo.co.uk", "hotmail.com", "outlook.com", "live.com", "icloud.com",
                   "aol.com", "ymail.com", "googlemail.com", "hotmail.co.uk", "mail.com", "protonmail.com"}


def _read_raw(raw_dir):
    out = []
    for path in sorted(glob.glob(os.path.join(str(raw_dir), "*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and (rec.get("name") or "").strip():
                    rec.setdefault("worker", os.path.basename(path).rsplit(".", 1)[0])
                    out.append(rec)
    return out


def _url(u):
    u = (u or "").strip()
    return u if u.startswith(("http://", "https://")) else None


def normalize(rec):
    """One raw record -> the dataset's shape, with everything unverifiable dropped."""
    name = " ".join(str(rec.get("name")).split())
    sources = [u for u in (_url(s) for s in rec.get("sources") or []) if u]
    lv = [k for k in (rec.get("levels") or []) if k in VALID_LEVELS] or levels.levels_from_name(name)
    kind = rec.get("kind") if rec.get("kind") in ("school", "office", "secretariat", "association", "ngo") else "school"
    if kind != "school" and "admin" not in lv:
        lv.append("admin")
    district = levels.canonical_district(rec.get("district")) or levels.district_from_text(
        rec.get("town"), rec.get("address"), rec.get("chiefdom"))
    emails, seen = [], set()
    for e in rec.get("emails") or []:
        if isinstance(e, str):
            e = {"email": e}
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
        num = levels.clean_phone(p.get("phone"))
        if num and num not in pseen:
            pseen.add(num)
            phones.append({"phone": num, "source_url": _url(p.get("source_url")) or (sources[0] if sources else None)})
    officials = []
    for o in rec.get("officials") or []:
        if not isinstance(o, dict) or not (o.get("name") or "").strip():
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
    for e in emails:
        sources.append(e["source_url"])
    own = rec.get("ownership") if rec.get("ownership") in VALID_OWNERSHIP else None
    denom = rec.get("denomination") or levels.faith_from_name(name)
    if not own and denom:
        own = "mission"
    return {
        "name": name, "kind": kind, "levels": lv, "district": district,
        "province": levels.province(district), "chiefdom": rec.get("chiefdom") or None, "town": rec.get("town") or None,
        "address": rec.get("address") or None, "ownership": own or "unknown", "denomination": denom,
        "website": _url(rec.get("website")), "emails": emails, "phones": phones, "officials": officials,
        "emis_code": str(rec["emis_code"]).strip() if rec.get("emis_code") else None,
        "lat": rec.get("lat") if isinstance(rec.get("lat"), (int, float)) else None,
        "lon": rec.get("lon") if isinstance(rec.get("lon"), (int, float)) else None,
        "sources": sorted(set(sources)), "notes": rec.get("notes") or None,
        "workers": [rec.get("worker")] if rec.get("worker") else [],
    }


def _fold(a, b):
    """Merge b into a (both normalized)."""
    for k in ("district", "province", "chiefdom", "town", "address", "denomination", "website", "emis_code", "lat",
              "lon", "notes"):
        if not a.get(k) and b.get(k):
            a[k] = b[k]
    if a.get("ownership") in (None, "unknown") and b.get("ownership") not in (None, "unknown"):
        a["ownership"] = b["ownership"]
    if len(b["name"]) > len(a["name"]) and levels.norm_name(b["name"]) == levels.norm_name(a["name"]):
        a["name"] = b["name"]
    a["levels"] = sorted(set(a["levels"]) | set(b["levels"]), key=lambda k: levels.BIT[k])
    have = {e["email"]: e for e in a["emails"]}
    for e in b["emails"]:
        if e["email"] in have:
            cur = have[e["email"]]
            if levels_conf(e) > levels_conf(cur):
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


def levels_conf(e):
    return db.CONF_RANK.get(e.get("confidence"), 0)


def merge(raw_dir=None, out_dir=None):
    raw_dir = raw_dir or config.RAW_DIR
    out_dir = out_dir or config.DATASET_DIR
    recs = [normalize(r) for r in _read_raw(raw_dir)]
    by_key, by_emis, by_name, merged = {}, {}, {}, []
    for r in recs:
        mk = levels.merge_key(r["name"])
        place = levels.place_key(r["town"], r["chiefdom"])
        key = (mk, r["district"], place)
        target = None
        if r["emis_code"]:
            # EMIS codes are reused across the Ministry's level lists, so a code only joins records whose
            # names agree.
            target = next((m for m in by_emis.get(r["emis_code"], []) if levels.similar(m["name"], r["name"]) >= .6),
                          None)
        if target is None and key in by_key:
            target = by_key[key]
        if target is None:
            # A record without a town (from a website or directory) joins the one same-named institution
            # in its district; with two or more candidates it stays separate rather than guess.
            cands = by_name.get((mk, r["district"]), [])
            if len(cands) == 1 and (not place or not levels.place_key(cands[0]["town"], cands[0]["chiefdom"])):
                target = cands[0]
            elif r["district"] is None:
                cands = [m for (k, d), ms in by_name.items() if k == mk for m in ms]
                if len(cands) == 1:
                    target = cands[0]
        if target is not None:
            _fold(target, r)
            r = target
        else:
            merged.append(r)
            by_name.setdefault((mk, r["district"]), []).append(r)
        by_key[(mk, r["district"], levels.place_key(r["town"], r["chiefdom"]))] = r
        by_key.setdefault(key, r)
        if r["emis_code"]:
            by_emis.setdefault(r["emis_code"], []).append(r)
    # An official email that turned up on two different institutions is ambiguous: keep it, but mark it low.
    owners = Counter(e["email"] for r in merged for e in r["emails"])
    for r in merged:
        for e in r["emails"]:
            if owners[e["email"]] > 1 and e["email"].split("@")[-1] in GENERIC_DOMAINS:
                e["confidence"] = "low"
        r["id"] = hashlib.sha1(f"{levels.merge_key(r['name'])}|{r['district']}|"
                               f"{levels.place_key(r['town'], r['chiefdom'])}|{r['emis_code']}".encode()).hexdigest()[:12]
    merged.sort(key=lambda r: (r["district"] or "~", levels.norm_name(r["name"])))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "sierra-leone-schools.jsonl"), "w", encoding="utf-8") as f:
        for r in merged:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    _write_csvs(merged, out_dir)
    stats = summarize(merged)
    stats["raw_records"] = len(recs)
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(stats, f, indent=2)
    return stats


def _write_csvs(merged, out_dir):
    with open(os.path.join(out_dir, "schools.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "kind", "levels", "district", "province", "chiefdom", "town", "ownership",
                    "denomination", "emis_code", "best_email", "email_confidence", "all_emails", "phones",
                    "head_or_official", "website", "sources"])
        for r in merged:
            best = sorted(r["emails"], key=lambda e: (-levels_conf(e), e["person"] is not None))
            head = next((f"{o['name']} ({o['role']})" if o["role"] else o["name"] for o in r["officials"]), "")
            w.writerow([r["id"], r["name"], r["kind"], ";".join(r["levels"]), r["district"] or "", r["province"] or "",
                        r["chiefdom"] or "", r["town"] or "", r["ownership"], r["denomination"] or "",
                        r["emis_code"] or "", best[0]["email"] if best else "", best[0]["confidence"] if best else "",
                        ";".join(e["email"] for e in r["emails"]), ";".join(p["phone"] for p in r["phones"]),
                        head, r["website"] or "", " ".join(r["sources"])])
    with open(os.path.join(out_dir, "contacts.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["institution_id", "institution", "district", "levels", "type", "value", "person", "role",
                    "confidence", "source_url"])
        for r in merged:
            for e in r["emails"]:
                w.writerow([r["id"], r["name"], r["district"] or "", ";".join(r["levels"]), "email", e["email"],
                            e["person"] or "", e["role"] or "", e["confidence"], e["source_url"]])
            for p in r["phones"]:
                w.writerow([r["id"], r["name"], r["district"] or "", ";".join(r["levels"]), "phone", p["phone"], "",
                            "", "", p["source_url"] or ""])
            for o in r["officials"]:
                w.writerow([r["id"], r["name"], r["district"] or "", ";".join(r["levels"]), "official", o["name"],
                            o["name"], o["role"] or "", "", o["source_url"] or ""])


def summarize(merged):
    emails = {e["email"] for r in merged for e in r["emails"]}
    by_level = Counter(k for r in merged for k in r["levels"])
    by_district = Counter(r["district"] or "Unknown" for r in merged)
    email_by_district = Counter(r["district"] or "Unknown" for r in merged if r["emails"])
    return {
        "institutions": len(merged),
        "with_email": sum(1 for r in merged if r["emails"]),
        "unique_emails": len(emails),
        "emails_by_confidence": dict(Counter(e["confidence"] for r in merged for e in r["emails"])),
        "with_phone": sum(1 for r in merged if r["phones"]),
        "with_named_official": sum(1 for r in merged if r["officials"]),
        "with_emis_code": sum(1 for r in merged if r["emis_code"]),
        "by_level": {k: by_level.get(k, 0) for k, *_ in levels.LEVELS},
        "by_district": dict(sorted(by_district.items())),
        "with_email_by_district": dict(sorted(email_by_district.items())),
        "by_ownership": dict(Counter(r["ownership"] for r in merged)),
    }


def load(conn, path=None):
    """Upsert the dataset into the CRM. Outreach stages, notes and manual contacts are kept."""
    path = path or config.DATASET
    t = db.now()
    stats = Counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            norm = levels.norm_name(r["name"])
            row = conn.execute("SELECT id, sources FROM schools WHERE ref=?", (r["id"],)).fetchone()
            vals = dict(ref=r["id"], name=r["name"], norm=norm, kind=r["kind"], levels=levels.mask(r["levels"]),
                        ownership=r["ownership"], denomination=r.get("denomination"), district=r.get("district"),
                        province=r.get("province"), chiefdom=r.get("chiefdom"), town=r.get("town"),
                        address=r.get("address"), lat=r.get("lat"), lon=r.get("lon"), emis_code=r.get("emis_code"),
                        notes=r.get("notes"))
            if row:
                sid = row["id"]
                sets = ", ".join(f"{k}=COALESCE(?, {k})" for k in vals)
                conn.execute(f"UPDATE schools SET {sets}, sources=?, updated_at=? WHERE id=?",
                             (*vals.values(), db.add_sources(row["sources"], *r["sources"]), t, sid))
                stats["updated"] += 1
            else:
                cols = ", ".join(vals)
                cur = conn.execute(
                    f"INSERT INTO schools({cols}, sources, created_at, updated_at) "
                    f"VALUES ({', '.join('?' for _ in vals)}, ?, ?, ?)",
                    (*vals.values(), json.dumps(r["sources"]), t, t))
                sid = cur.lastrowid
                stats["added"] += 1
            for e in r["emails"]:
                db.upsert_contact(conn, sid, "email", e["email"], "research", e.get("person"), e.get("role"),
                                  e["source_url"], e["confidence"], t)
            for p in r["phones"]:
                db.upsert_contact(conn, sid, "phone", p["phone"], "research", source_url=p.get("source_url"), ts=t)
            for o in r["officials"]:
                db.upsert_contact(conn, sid, "person", o["name"], "research", o["name"], o.get("role"),
                                  o.get("source_url"), ts=t)
            if r.get("website"):
                db.upsert_contact(conn, sid, "website", r["website"], "research", ts=t)
            db.refresh_primary(conn, sid)
    conn.commit()
    return dict(stats)
