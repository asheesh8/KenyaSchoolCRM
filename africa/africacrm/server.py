"""The CRM: a JSON API over every country's directory, the shared sender accounts, the email
queue and the WhatsApp queue, plus the static UI in ui/."""

import csv
import hashlib
import hmac
import io
import json
import mimetypes
import re
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from . import config, db, levels, mailer, phone
from .countries import COUNTRIES, get
from .countries import public as public_countries

_local = threading.local()


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def conn():
    c = getattr(_local, "conn", None)
    if c is None:
        c = _local.conn = db.connect()
    return c


SORTS = {
    "best": ["(s.email IS NOT NULL) DESC", "(s.mobile IS NOT NULL) DESC", "(s.leader IS NOT NULL) DESC",
             "(s.phone IS NOT NULL) DESC", "CASE s.confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END",
             "s.name COLLATE NOCASE"],
    "name": ["s.name COLLATE NOCASE {dir}"],
    "district": ["s.country {dir}", "s.district {dir}", "s.name COLLATE NOCASE"],
    "status": ["s.status {dir}", "s.name COLLATE NOCASE"],
    "touched": ["s.touched_at {dir} NULLS LAST"],
    "students": ["s.students {dir} NULLS LAST"],
}
LIST_COLS = """s.id, s.country, s.name, s.kind, s.levels, s.ownership, s.denomination, s.province, s.district, s.area,
    s.town, s.emis_code, s.students, s.email, s.phone, s.mobile, s.website, s.leader, s.confidence, s.status,
    s.starred, s.tags, s.touched_at, s.whatsapp_status, s.whatsapp_at,
    (SELECT COUNT(*) FROM contacts k WHERE k.school_id=s.id AND k.kind='email' AND k.active=1) AS n_emails,
    (SELECT e.status || ':' || e.next_step FROM enrollments e WHERE e.school_id=s.id
       ORDER BY e.updated_at DESC LIMIT 1) AS sequence"""
MULTI = ("country", "district", "province", "status", "ownership", "denomination", "kind", "confidence", "setting",
         "gender", "boarding", "whatsapp")


def build_filter(p):
    where, params = [], []

    def multi(key):
        v = p.get(key)
        if isinstance(v, list):
            return [str(x) for x in v if x]
        return [x for x in str(v).split(",") if x] if v else []

    q = (p.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        where.append("(s.name LIKE ? OR s.town LIKE ? OR s.area LIKE ? OR s.district LIKE ? OR s.leader LIKE ? "
                     "OR s.email LIKE ? OR s.emis_code LIKE ? OR EXISTS (SELECT 1 FROM contacts k WHERE "
                     "k.school_id=s.id AND k.value LIKE ?))")
        params += [like] * 8
    for key in MULTI:
        col = "s.whatsapp_status" if key == "whatsapp" else f"s.{key}"
        vals = [v.upper() for v in multi(key)] if key == "country" else multi(key)
        if vals:
            named = [v for v in vals if v not in ("none", "NONE")]
            parts = ([f"{col} IN ({','.join('?' * len(named))})"] if named else []) + \
                    ([f"{col} IS NULL"] if len(named) < len(vals) else [])
            where.append("(" + " OR ".join(parts) + ")")
            params += named
    lv = multi("level")
    if lv:
        m = levels.mask(lv)
        where.append(f"(s.levels & {m}" + (" OR s.levels = 0)" if "unknown" in lv else ")"))
    for h in multi("has"):
        if h in ("email", "phone", "mobile", "website", "leader", "emis_code"):
            where.append(f"s.{h} IS NOT NULL")
        elif h == "contact":
            where.append("(s.email IS NOT NULL OR s.phone IS NOT NULL)")
    for h in multi("missing"):
        if h in ("email", "phone", "mobile", "website", "leader"):
            where.append(f"s.{h} IS NULL")
    seq = p.get("sequence")
    if seq == "none":
        where.append("NOT EXISTS (SELECT 1 FROM enrollments e WHERE e.school_id=s.id)")
    elif seq:
        where.append("EXISTS (SELECT 1 FROM enrollments e WHERE e.school_id=s.id AND e.status=?)")
        params.append(seq)
    if p.get("campaign"):
        where.append("EXISTS (SELECT 1 FROM enrollments e WHERE e.school_id=s.id AND e.campaign=?)")
        params.append(p["campaign"])
    if str(p.get("starred")) == "1":
        where.append("s.starred=1")
    if p.get("tag"):
        where.append("EXISTS (SELECT 1 FROM json_each(s.tags) WHERE json_each.value=?)")
        params.append(p["tag"])
    for key, op in (("min_students", ">="), ("max_students", "<=")):
        if str(p.get(key) or "").isdigit():
            where.append(f"s.students {op} ?")
            params.append(int(p[key]))
    return ("WHERE " + " AND ".join(where)) if where else "", params


def _row(r):
    d = dict(r)
    for k in ("tags", "sources"):
        if k in d:
            d[k] = json.loads(d.get(k) or "[]")
    d["level_keys"] = levels.keys(d.get("levels") or 0)
    return d


def api_schools(p):
    where, params = build_filter(p)
    sort = p.get("sort") if p.get("sort") in SORTS else "best"
    direction = "DESC" if p.get("dir") == "desc" else "ASC"
    order = ", ".join(x.format(dir=direction) for x in SORTS[sort])
    per = min(int(p.get("per") or 50), 500)
    page = max(int(p.get("page") or 1), 1)
    c = conn()
    counts = c.execute(f"SELECT COUNT(*), SUM(s.email IS NOT NULL), SUM(s.mobile IS NOT NULL) FROM schools s {where}",
                       params).fetchone()
    rows = c.execute(f"SELECT {LIST_COLS} FROM schools s {where} ORDER BY {order} LIMIT ? OFFSET ?",
                     params + [per, (page - 1) * per]).fetchall()
    return {"total": counts[0], "with_email": counts[1] or 0, "with_mobile": counts[2] or 0, "page": page,
            "per": per, "rows": [_row(r) for r in rows]}


def matching_ids(p):
    where, params = build_filter(p)
    return [r[0] for r in conn().execute(f"SELECT s.id FROM schools s {where}", params).fetchall()]


def api_school(sid):
    c = conn()
    r = c.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    if not r:
        return None
    d = _row(r)
    cty = get(r["country"])
    d["contacts"] = [dict(x) for x in c.execute(
        "SELECT * FROM contacts WHERE school_id=? ORDER BY active DESC, kind, "
        "CASE confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END", (sid,))]
    sup = {x[0] for x in c.execute("SELECT email FROM suppressions")}
    msgs = mailer.phone_messages(c, r)
    for k in d["contacts"]:
        k["suppressed"] = k["kind"] == "email" and k["value"] in sup
        if k["kind"] == "phone":
            k["mobile"] = cty.is_mobile(k["value"])
            k["links"] = phone.links(r, k["value"], msgs)
    d["activities"] = [dict(x) for x in c.execute(
        "SELECT * FROM activities WHERE school_id=? ORDER BY created_at DESC LIMIT 100", (sid,))]
    d["enrollments"] = [dict(x) for x in c.execute(
        "SELECT e.*, a.label AS account_label FROM enrollments e LEFT JOIN accounts a ON a.id=e.account_id "
        "WHERE e.school_id=?", (sid,))]
    d["phone_messages"] = msgs
    return d


def api_patch_school(sid, body):
    c = conn()
    r = c.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    if not r:
        return None
    if "status" in body and body["status"] in db.STATUSES and body["status"] != r["status"]:
        c.execute("UPDATE schools SET status=? WHERE id=?", (body["status"], sid))
        labels = dict(zip(db.STATUSES, STAGE_LABELS))
        db.log_activity(c, sid, "status", f"Stage: {labels[r['status']]} → {labels[body['status']]}")
        if body["status"] in ("do_not_contact", "not_interested"):
            c.execute("UPDATE enrollments SET status='unsubscribed', updated_at=? WHERE school_id=? AND status='active'",
                      (db.now(), sid))
    if "starred" in body:
        c.execute("UPDATE schools SET starred=? WHERE id=?", (1 if body["starred"] else 0, sid))
    if "tags" in body and isinstance(body["tags"], list):
        c.execute("UPDATE schools SET tags=? WHERE id=?", (json.dumps(sorted({str(t)[:40] for t in body["tags"]})), sid))
    if "notes" in body:
        c.execute("UPDATE schools SET notes=? WHERE id=?", (str(body["notes"])[:5000], sid))
    c.execute("UPDATE schools SET updated_at=? WHERE id=?", (db.now(), sid))
    c.commit()
    return api_school(sid)


STAGE_LABELS = ["New", "In email sequence", "Contacted", "Replied", "Interested", "Partner", "Not interested",
                "Do not contact"]


def api_bulk(body):
    c = conn()
    ids = [int(i) for i in body.get("ids") or []]
    if body.get("filter") is not None:
        ids = matching_ids(body["filter"])
    for sid in ids:
        if body.get("status") in db.STATUSES:
            api_patch_school(sid, {"status": body["status"]})
        if "starred" in body:
            c.execute("UPDATE schools SET starred=? WHERE id=?", (1 if body["starred"] else 0, sid))
        if body.get("tag"):
            r = c.execute("SELECT tags FROM schools WHERE id=?", (sid,)).fetchone()
            if r:
                c.execute("UPDATE schools SET tags=? WHERE id=?",
                          (json.dumps(sorted(set(json.loads(r[0])) | {body["tag"][:40]})), sid))
    c.commit()
    return {"updated": len(ids)}


def api_activity(sid, body):
    kind = body.get("kind") if body.get("kind") in ("note", "call", "email", "whatsapp", "sms", "meeting",
                                                     "visit") else "note"
    c = conn()
    db.log_activity(c, sid, kind, str(body.get("body") or "")[:5000])
    c.commit()
    return api_school(sid)


def api_add_contact(sid, body):
    c = conn()
    r = c.execute("SELECT country FROM schools WHERE id=?", (sid,)).fetchone()
    if not r:
        return None
    kind = body.get("kind")
    value = str(body.get("value") or "").strip()
    if kind == "email":
        value = levels.clean_email(value)
    elif kind == "phone":
        value = get(r["country"]).clean_phone(value) or value
    if kind not in ("email", "phone", "website", "person") or not value:
        return {"error": "Check the value."}
    db.upsert_contact(c, sid, kind, value, "manual", body.get("person") or (value if kind == "person" else None),
                      body.get("role") or None, body.get("source_url"), "high")
    db.refresh_primary(c, sid, r["country"])
    c.commit()
    return api_school(sid)


def api_patch_contact(cid, body):
    c = conn()
    r = c.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    if not r:
        return None
    if "active" in body:
        c.execute("UPDATE contacts SET active=? WHERE id=?", (1 if body["active"] else 0, cid))
    db.refresh_primary(c, r["school_id"])
    c.commit()
    return api_school(r["school_id"])


# ---------- dashboards ----------

def _counts(c, where="", params=()):
    r = c.execute(
        f"""SELECT COUNT(*) AS total, SUM(kind='school') AS schools, SUM(kind!='school') AS offices,
              SUM(email IS NOT NULL) AS with_email, SUM(phone IS NOT NULL) AS with_phone,
              SUM(mobile IS NOT NULL) AS with_mobile, SUM(leader IS NOT NULL) AS with_leader,
              SUM(status NOT IN ('new','queued')) AS contacted,
              SUM(status IN ('replied','interested','partner')) AS replied,
              SUM(status IN ('interested','partner')) AS interested
            FROM schools {where}""", params).fetchone()
    return {k: r[k] or 0 for k in r.keys()}


def api_summary(country=None):
    c = conn()
    out = {"sent_total": c.execute("SELECT COUNT(*) FROM messages WHERE status='sent'" +
                                   (" AND country=?" if country else ""), (country,) if country else ()).fetchone()[0]}
    where, params = ("WHERE country=?", (country,)) if country else ("", ())
    out.update(_counts(c, where, params))
    out["statuses"] = {r[0]: r[1] for r in c.execute(f"SELECT status, COUNT(*) FROM schools {where} GROUP BY status",
                                                      params)}
    out["whatsapp"] = {r[0] or "not yet": r[1] for r in c.execute(
        f"SELECT whatsapp_status, COUNT(*) FROM schools {where} {'AND' if where else 'WHERE'} mobile IS NOT NULL "
        f"GROUP BY whatsapp_status", params)}
    out["sequence"] = {r[0]: r[1] for r in c.execute(
        "SELECT status, COUNT(*) FROM enrollments" + (" WHERE country=?" if country else "") + " GROUP BY status",
        params)}
    out["recent"] = [dict(r) for r in c.execute(
        "SELECT a.*, s.name, s.country FROM activities a JOIN schools s ON s.id=a.school_id "
        + ("WHERE s.country=? " if country else "") + "ORDER BY a.created_at DESC LIMIT 12", params)]
    if not country:
        out["countries"] = []
        for code, cty in COUNTRIES.items():
            d = _counts(c, "WHERE country=?", (code,))
            d.update(code=code, name=cty.name, flag=cty.flag,
                     emailed=c.execute("SELECT COUNT(DISTINCT school_id) FROM messages WHERE status='sent' AND "
                                       "country=?", (code,)).fetchone()[0],
                     whatsapped=c.execute("SELECT COUNT(*) FROM schools WHERE country=? AND whatsapp_status IN "
                                          "('sent','replied')", (code,)).fetchone()[0])
            out["countries"].append(d)
        out["by_level"] = [{"key": k, "label": levels.LABEL[k],
                            "schools": c.execute(f"SELECT COUNT(*) FROM schools WHERE levels & {b}").fetchone()[0],
                            "with_email": c.execute(f"SELECT COUNT(*) FROM schools WHERE levels & {b} AND email IS NOT "
                                                    "NULL").fetchone()[0]} for k, b, _ in levels.LEVELS]
        return out
    cty = get(country)
    out["country"] = cty.public()
    out["by_level"] = [{"key": lv["value"], "label": lv["label"], "detail": lv["detail"],
                        **{k: c.execute(f"SELECT COUNT(*) FROM schools WHERE country=? AND levels & {levels.BIT[lv['value']]}"
                                        + extra, (country,)).fetchone()[0]
                           for k, extra in (("schools", ""), ("with_email", " AND email IS NOT NULL"),
                                            ("with_mobile", " AND mobile IS NOT NULL"))}}
                       for lv in cty.public()["levels"]]
    regions = {r["district"]: dict(r) for r in c.execute("SELECT * FROM regions WHERE country=?", (country,))}
    rows = []
    for r in c.execute(
            """SELECT COALESCE(district, '') AS district, MAX(province) AS province, COUNT(*) AS schools,
                 SUM(email IS NOT NULL) AS with_email, SUM(mobile IS NOT NULL) AS with_mobile,
                 SUM(status NOT IN ('new','queued')) AS contacted, SUM(status IN ('replied','interested','partner'))
                 AS replied FROM schools WHERE country=? GROUP BY COALESCE(district, '')""", (country,)):
        d = dict(r)
        reg = regions.pop(d["district"], {})
        d.update(province=d["province"] or reg.get("province"), census=reg.get("census_schools"),
                 population=reg.get("population"), school_age=reg.get("school_age"))
        rows.append(d)
    for name, reg in regions.items():  # districts with nothing on file yet still show
        rows.append({"district": name, "province": reg["province"], "schools": 0, "with_email": 0, "with_mobile": 0,
                     "contacted": 0, "replied": 0, "census": reg["census_schools"], "population": reg["population"],
                     "school_age": reg["school_age"]})
    rows.sort(key=lambda d: (d["district"] == "", -(d["schools"] or 0)))
    out["by_district"] = rows
    out["email_confidence"] = {r[0] or "unknown": r[1] for r in c.execute(
        "SELECT k.confidence, COUNT(DISTINCT k.value) FROM contacts k JOIN schools s ON s.id=k.school_id "
        "WHERE s.country=? AND k.kind='email' AND k.active=1 GROUP BY k.confidence", (country,))}
    out["ownership"] = {r[0] or "unknown": r[1] for r in c.execute(
        "SELECT ownership, COUNT(*) FROM schools WHERE country=? GROUP BY ownership", (country,))}
    return out


def api_facets(country=None):
    c = conn()
    where, params = ("WHERE country=?", (country,)) if country else ("", ())
    out = {
        "countries": public_countries(),
        "statuses": db.STATUSES,
        "denominations": [r[0] for r in c.execute(
            f"SELECT denomination FROM schools {where} {'AND' if where else 'WHERE'} denomination IS NOT NULL "
            "GROUP BY denomination ORDER BY COUNT(*) DESC LIMIT 30", params)],
        "tags": sorted({t for r in c.execute(f"SELECT tags FROM schools {where} {'AND' if where else 'WHERE'} "
                                             "tags!='[]'", params) for t in json.loads(r[0])}),
        "campaigns": [r[0] for r in c.execute("SELECT campaign FROM enrollments WHERE campaign IS NOT NULL "
                                              "GROUP BY campaign ORDER BY MAX(created_at) DESC")],
        "has_extra": {k: bool(c.execute(f"SELECT 1 FROM schools {where} {'AND' if where else 'WHERE'} {k} IS NOT NULL "
                                        "LIMIT 1", params).fetchone()) for k in ("setting", "gender", "boarding",
                                                                                  "students")},
    }
    if country:
        cty = get(country)
        known = {}
        for r in c.execute("SELECT district, province FROM regions WHERE country=?", (country,)):
            known[r[0]] = r[1]
        for r in c.execute("SELECT district, MAX(province), COUNT(*) FROM schools WHERE country=? AND district IS NOT "
                           "NULL GROUP BY district", (country,)):
            known[r[0]] = known.get(r[0]) or r[1]
        out["districts"] = [{"value": d, "province": p} for d, p in sorted(known.items())]
        out["provinces"] = sorted({p for p in known.values() if p})
        if hasattr(cty, "regions"):
            out["provinces"] = cty.regions
    return out


def api_pipeline(p):
    where, params = build_filter(p)
    c = conn()
    out = {}
    for st in db.STATUSES:
        w = (where + " AND " if where else "WHERE ") + "s.status=?"
        out[st] = {"count": c.execute(f"SELECT COUNT(*) FROM schools s {w}", params + [st]).fetchone()[0],
                   "rows": [_row(r) for r in c.execute(
                       f"SELECT {LIST_COLS} FROM schools s {w} ORDER BY s.touched_at DESC NULLS LAST, s.name LIMIT 40",
                       params + [st])]}
    return out


def api_export(p):
    where, params = build_filter(p)
    c = conn()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Country", "Name", "Type", "Levels", "Province / region", "District / county", "Area", "Town",
                "Ownership", "Denomination", "EMIS / school code", "Pupils", "Best email", "Email confidence",
                "All emails", "Phones", "WhatsApp number", "Head / official", "Website", "Stage", "WhatsApp",
                "Sources"])
    for r in c.execute(f"SELECT s.* FROM schools s {where} ORDER BY s.country, s.district, s.name", params):
        cty = get(r["country"])
        cs = c.execute("SELECT kind, value FROM contacts WHERE school_id=? AND active=1", (r["id"],)).fetchall()
        w.writerow([cty.name, r["name"], r["kind"], ", ".join(cty.level_labels.get(k, k) for k in levels.keys(r["levels"])),
                    r["province"], r["district"], r["area"], r["town"], r["ownership"], r["denomination"],
                    r["emis_code"], r["students"], r["email"], r["confidence"],
                    "; ".join(x["value"] for x in cs if x["kind"] == "email"),
                    "; ".join(x["value"] for x in cs if x["kind"] == "phone"), r["mobile"], r["leader"], r["website"],
                    r["status"], r["whatsapp_status"], " ".join(json.loads(r["sources"]))])
    return "﻿" + buf.getvalue()


# ---------- email ----------

ACCOUNT_FIELDS = {"label": str, "from_name": str, "from_email": str, "reply_to": str, "provider": str,
                  "smtp_host": str, "smtp_port": int, "smtp_security": str, "imap_host": str, "imap_port": int,
                  "username": str, "daily_cap": int, "hourly_cap": int, "min_gap_s": int, "warmup": int,
                  "warmup_start": int, "warmup_step": int, "window_start": int, "window_end": int, "signature": str,
                  "enabled": int, "countries": str}
LIMITS = {"daily_cap": (1, 500), "hourly_cap": (1, 100), "min_gap_s": (30, 3600), "warmup_start": (1, 200),
          "warmup_step": (0, 100), "window_start": (0, 23), "window_end": (1, 24), "smtp_port": (1, 65535),
          "imap_port": (1, 65535)}


def _clean_account(body):
    out = {}
    for k, typ in ACCOUNT_FIELDS.items():
        if k in body and body[k] is not None:
            v = body[k]
            if typ is int:
                v = int(bool(v)) if k in ("warmup", "enabled") else int(v)
                lo, hi = LIMITS.get(k, (None, None))
                if lo is not None:
                    v = max(lo, min(hi, v))
            elif k == "countries":
                vals = v if isinstance(v, list) else str(v).split(",")
                v = ",".join(x.strip().upper() for x in vals if x.strip().upper() in COUNTRIES)
            else:
                v = str(v).strip()[:2000]
            out[k] = v
    if "smtp_security" in out and out["smtp_security"] not in ("starttls", "ssl", "none"):
        out["smtp_security"] = "starttls"
    if "from_email" in out and not levels.clean_email(out["from_email"]):
        raise ValueError("That sender email doesn't look right.")
    return out


def api_accounts():
    c = conn()
    s = mailer.settings(c)
    out = []
    for a in c.execute("SELECT * FROM accounts ORDER BY id"):
        d = mailer.public_account(a)
        ok, reason, info = mailer.allowance(c, a, weekdays_only=s["weekdays_only"])
        d.update(info, ready=ok, state=reason, country_list=mailer.account_countries(a),
                 active=c.execute("SELECT COUNT(*) FROM enrollments WHERE account_id=? AND status='active'",
                                  (a["id"],)).fetchone()[0],
                 due=c.execute("SELECT COUNT(*) FROM enrollments WHERE account_id=? AND status='active' AND "
                               "next_due_at<=?", (a["id"], time.time())).fetchone()[0],
                 replied=c.execute("SELECT COUNT(*) FROM enrollments WHERE account_id=? AND status='replied'",
                                   (a["id"],)).fetchone()[0])
        out.append(d)
    return {"accounts": out, "max": config.MAX_ACCOUNTS,
            "presets": {k: dict(v) for k, v in mailer.PRESETS.items()}}


def api_create_account(body):
    c = conn()
    if c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] >= config.MAX_ACCOUNTS:
        return {"error": f"You can connect up to {config.MAX_ACCOUNTS} sender accounts."}
    preset = mailer.PRESETS.get(body.get("provider") or "custom", mailer.PRESETS["custom"])
    merged = {k: v for k, v in preset.items() if k != "help"}
    merged.update({k: v for k, v in body.items() if v not in (None, "")})
    merged.setdefault("username", body.get("from_email"))
    merged.setdefault("label", body.get("from_email"))
    vals = _clean_account(merged)
    for k in ("from_email", "smtp_host", "username"):
        if not vals.get(k):
            return {"error": f"Missing {k.replace('_', ' ')}."}
    if c.execute("SELECT 1 FROM accounts WHERE lower(from_email)=?", (vals["from_email"].lower(),)).fetchone():
        return {"error": "That email is already connected."}
    used = {r[0] for r in c.execute("SELECT id FROM accounts")}
    vals["id"] = next(i for i in range(1, config.MAX_ACCOUNTS + 1) if i not in used)
    vals["password_enc"] = mailer.encrypt(body.get("password") or "")
    vals["created_at"] = db.now()
    c.execute(f"INSERT INTO accounts({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", list(vals.values()))
    c.commit()
    return api_accounts()


def api_patch_account(aid, body):
    c = conn()
    if not c.execute("SELECT 1 FROM accounts WHERE id=?", (aid,)).fetchone():
        return None
    vals = _clean_account(body)
    if body.get("password"):
        vals["password_enc"] = mailer.encrypt(body["password"])
    if vals.get("enabled") == 1:
        vals["fail_streak"] = 0
        vals["last_error"] = None
    if vals:
        c.execute(f"UPDATE accounts SET {', '.join(f'{k}=?' for k in vals)} WHERE id=?", (*vals.values(), aid))
        c.commit()
    return api_accounts()


def api_delete_account(aid, body):
    c = conn()
    active = c.execute("SELECT COUNT(*) FROM enrollments WHERE account_id=? AND status='active'", (aid,)).fetchone()[0]
    move_to = body.get("move_to")
    if active and not move_to:
        return {"error": f"{active} contacts are still in this account's sequence. Move them to another account first."}
    if move_to:
        c.execute("UPDATE enrollments SET account_id=? WHERE account_id=? AND status='active'", (int(move_to), aid))
    c.execute("UPDATE enrollments SET status='paused' WHERE account_id=? AND status='active'", (aid,))
    c.execute("DELETE FROM accounts WHERE id=?", (aid,))
    c.commit()
    return api_accounts()


def api_campaigns(country=None):
    c = conn()
    w, params = (" WHERE e.country=?", (country,)) if country else ("", ())
    out = []
    for r in c.execute(
            f"""SELECT COALESCE(e.campaign, '(no name)') AS campaign, MIN(e.country) AS country,
                  COUNT(DISTINCT e.country) AS n_countries, COUNT(*) AS addresses, MIN(e.created_at) AS started,
                  SUM(e.status='active') AS active, SUM(e.status='paused') AS paused, SUM(e.status='done') AS done,
                  SUM(e.status='replied') AS replied, SUM(e.status='unsubscribed') AS unsubscribed,
                  SUM(e.status='bounced') AS bounced,
                  (SELECT COUNT(*) FROM messages m JOIN enrollments e2 ON e2.id=m.enrollment_id
                    WHERE m.status='sent' AND COALESCE(e2.campaign, '(no name)')=COALESCE(e.campaign, '(no name)'))
                    AS sent
                FROM enrollments e{w} GROUP BY COALESCE(e.campaign, '(no name)') ORDER BY started DESC""", params):
        out.append(dict(r))
    return out


def api_outreach(country=None):
    c = conn()
    s = mailer.settings(c)
    cw, cp = (" WHERE country=?", (country,)) if country else ("", ())
    ca = (" AND e.country=?" if country else "")
    return {
        "settings": s, "public_url": config.PUBLIC_URL, "on_vercel": config.ON_VERCEL,
        "cron": bool(config.CRON_SECRET),
        "accounts": api_accounts()["accounts"], "max_accounts": config.MAX_ACCOUNTS,
        "sequence": {r[0]: r[1] for r in c.execute(f"SELECT status, COUNT(*) FROM enrollments{cw} GROUP BY status", cp)},
        "by_step": {r[0]: r[1] for r in c.execute(
            "SELECT next_step, COUNT(*) FROM enrollments WHERE status='active'" + (" AND country=?" if country else "")
            + " GROUP BY next_step", cp)},
        "sent": c.execute("SELECT COUNT(*) FROM messages WHERE status='sent'" + (" AND country=?" if country else ""),
                          cp).fetchone()[0],
        "sent_today": c.execute("SELECT COUNT(*) FROM messages WHERE status='sent' AND created_at>=?",
                                (time.time() - time.time() % 86400,)).fetchone()[0],
        "suppressed": c.execute("SELECT COUNT(*) FROM suppressions").fetchone()[0],
        "forecast": mailer.forecast(c),
        "campaigns": api_campaigns(country),
        "recent": [dict(r) for r in c.execute(
            "SELECT m.*, s.name AS school, a.label AS account FROM messages m LEFT JOIN schools s ON s.id=m.school_id "
            "LEFT JOIN accounts a ON a.id=m.account_id" + (" WHERE m.country=?" if country else "")
            + " ORDER BY m.created_at DESC LIMIT 30", cp)],
        "upcoming": [dict(r) for r in c.execute(
            "SELECT e.*, s.name AS school, a.label AS account FROM enrollments e JOIN schools s ON s.id=e.school_id "
            f"LEFT JOIN accounts a ON a.id=e.account_id WHERE e.status='active'{ca} ORDER BY e.next_due_at LIMIT 30",
            cp)],
        "templates": [dict(r) for r in c.execute("SELECT * FROM templates ORDER BY country, step")],
    }


def api_enroll(body):
    c = conn()
    ids = [int(i) for i in body.get("ids") or []]
    if body.get("filter") is not None:
        f = dict(body["filter"])
        f["has"] = ",".join(sorted(set(str(f.get("has") or "").split(",")) - {""} | {"email"}))
        ids = matching_ids(f)
    if body.get("dry_run"):
        if not ids:
            return {"schools": 0, "with_email": 0, "by_country": {}}
        rows = []
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            rows += c.execute(
                f"SELECT country, email, status FROM schools s WHERE id IN ({','.join('?' * len(chunk))}) AND NOT "
                "EXISTS (SELECT 1 FROM enrollments e WHERE e.email=s.email) AND NOT EXISTS (SELECT 1 FROM "
                "suppressions x WHERE x.email=s.email)", chunk).fetchall()
        by = {}
        for r in rows:
            if r["email"] and r["status"] not in ("do_not_contact", "not_interested"):
                by[r["country"]] = by.get(r["country"], 0) + 1
        return {"schools": len(ids), "with_email": sum(by.values()), "by_country": by}
    stats = mailer.enroll(c, ids, body.get("account_id") or None, body.get("mode") or "best",
                          campaign=(str(body.get("campaign") or "").strip()[:80] or None),
                          spread_hours=float(body.get("spread_hours") or 0))
    stats["schools"] = len(ids)
    return stats


def api_preview(body):
    c = conn()
    sid = int(body.get("school_id") or 0)
    country = (body.get("country") or "").upper() or None
    if sid:
        s = c.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    else:
        s = c.execute("SELECT * FROM schools WHERE email IS NOT NULL" + (" AND country=?" if country else "") +
                      " ORDER BY (leader IS NOT NULL) DESC LIMIT 1", (country,) if country else ()).fetchone()
    acc = c.execute("SELECT * FROM accounts WHERE id=?", (body.get("account_id") or 0,)).fetchone() or \
        c.execute("SELECT * FROM accounts ORDER BY id LIMIT 1").fetchone()
    if not s:
        return {"error": "No school with an email to preview with yet."}
    acc = acc or {"from_name": "Your name", "label": "Your name", "signature": "", "from_email": "you@example.org",
                  "reply_to": None}
    p = c.execute("SELECT value, role FROM contacts WHERE school_id=? AND kind='person' AND active=1 LIMIT 1",
                  (s["id"],)).fetchone()
    enr = {"person": p["value"] if p else None, "role": p["role"] if p else None, "email": s["email"] or "",
           "thread_subject": None}
    out = []
    for step in mailer.steps(c, s["country"]):
        subj, body_ = mailer.compose(c, acc, s, enr, step)
        if step == 1:
            enr["thread_subject"] = subj
        out.append({"step": step, "subject": subj, "body": body_})
    return {"school": s["name"], "country": get(s["country"]).name, "to": s["email"], "emails": out}


def api_enrollment_action(eid, body):
    c = conn()
    e = c.execute("SELECT * FROM enrollments WHERE id=?", (eid,)).fetchone()
    if not e:
        return None
    act = body.get("action")
    if act == "pause" and e["status"] == "active":
        c.execute("UPDATE enrollments SET status='paused', updated_at=? WHERE id=?", (db.now(), eid))
    elif act == "resume" and e["status"] == "paused":
        c.execute("UPDATE enrollments SET status='active', next_due_at=MAX(next_due_at, ?), updated_at=? WHERE id=?",
                  (db.now(), db.now(), eid))
    elif act == "replied":
        mailer.classify_inbound(c, e["email"], "", "")
    elif act == "unsubscribe":
        mailer.suppress(c, e["email"], "manual")
    elif act == "move" and body.get("account_id"):
        c.execute("UPDATE enrollments SET account_id=?, updated_at=? WHERE id=?", (int(body["account_id"]), db.now(), eid))
    elif act == "remove":
        c.execute("DELETE FROM enrollments WHERE id=?", (eid,))
    c.commit()
    return {"ok": True}


def api_bulk_enrollments(body):
    """Pause / resume / remove a whole campaign."""
    c = conn()
    camp, act = body.get("campaign"), body.get("action")
    cond = "COALESCE(campaign, '(no name)')=?"
    if act == "pause":
        cur = c.execute(f"UPDATE enrollments SET status='paused', updated_at=? WHERE {cond} AND status='active'",
                        (db.now(), camp))
    elif act == "resume":
        cur = c.execute(f"UPDATE enrollments SET status='active', next_due_at=MAX(next_due_at, ?), updated_at=? "
                        f"WHERE {cond} AND status='paused'", (db.now(), db.now(), camp))
    else:
        return {"error": "Unknown action."}
    c.commit()
    return {"updated": cur.rowcount}


def api_replies(p):
    c = conn()
    country = (p.get("country") or "").upper() or None
    w, params = (" AND e.country=?", [country]) if country else ("", [])
    email = [dict(r) for r in c.execute(
        "SELECT e.id, e.school_id, e.country, e.email, e.person, e.campaign, e.replied_at, e.reply_snippet, "
        "e.updated_at, s.name AS school, s.status, s.district, a.label AS account, a.from_email AS account_email "
        "FROM enrollments e JOIN schools s ON s.id=e.school_id LEFT JOIN accounts a ON a.id=e.account_id "
        f"WHERE e.status='replied'{w} ORDER BY COALESCE(e.replied_at, e.updated_at) DESC LIMIT 300", params)]
    wa = [dict(r) for r in c.execute(
        "SELECT s.id AS school_id, s.country, s.name AS school, s.status, s.district, s.mobile, s.whatsapp_at "
        "FROM schools s WHERE s.whatsapp_status='replied'" + (" AND s.country=?" if country else "")
        + " ORDER BY s.whatsapp_at DESC LIMIT 300", params)]
    stops = c.execute("SELECT COUNT(*) FROM suppressions WHERE reason IN ('replied_stop','unsubscribed')").fetchone()[0]
    return {"email": email, "whatsapp": wa, "stops": stops}


def api_suppress(body):
    c = conn()
    n = 0
    for e in re.split(r"[\s,;]+", str(body.get("emails") or "")):
        e = levels.clean_email(e)
        if e:
            mailer.suppress(c, e, body.get("reason") or "manual")
            n += 1
    return {"added": n}


def api_templates(method, country, step, body):
    c = conn()
    country = "" if country in ("", "_", "all") else country.upper()
    if country and country not in COUNTRIES:
        raise ValueError("Unknown country.")
    if method == "POST" and step is None:  # give this country its own copy of the emails
        for t in c.execute("SELECT * FROM templates WHERE country='' ORDER BY step").fetchall():
            c.execute("INSERT OR IGNORE INTO templates(country, step, name, subject, body, delay_days) "
                      "VALUES (?,?,?,?,?,?)", (country, t["step"], t["name"], t["subject"], t["body"],
                                               t["delay_days"]))
        c.commit()
    elif method == "DELETE" and step is None and country:
        c.execute("DELETE FROM templates WHERE country=?", (country,))
        c.commit()
    elif method in ("PUT", "PATCH") and step is not None:
        c.execute("UPDATE templates SET name=COALESCE(?, name), subject=COALESCE(?, subject), "
                  "body=COALESCE(?, body), delay_days=COALESCE(?, delay_days) WHERE country=? AND step=?",
                  (body.get("name"), body.get("subject"), body.get("body"),
                   max(0.0, float(body["delay_days"])) if body.get("delay_days") not in (None, "") else None,
                   country, step))
        c.commit()
    return api_outreach()


def api_settings(body):
    c = conn()
    for k in ("org_name", "library_link", "phone_sender"):
        if k in body:
            db.set_meta(c, k, str(body[k])[:500])
    if "whatsapp_daily_target" in body:
        db.set_meta(c, "whatsapp_daily_target", max(1, min(500, int(body["whatsapp_daily_target"] or 40))))
    code = (body.get("country") or "").upper()
    for k in mailer.DEFAULT_PHONE_MESSAGES:
        if k in body:
            db.set_meta(c, f"{k}:{code}" if code in COUNTRIES else k, str(body[k])[:2000])
    if "weekdays_only" in body:
        db.set_meta(c, "weekdays_only", "1" if body["weekdays_only"] else "0")
    return api_outreach()


UNSUB_PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unsubscribed</title><body style="font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem;
line-height:1.5"><h1 style="font-size:1.4rem">{title}</h1><p>{body}</p></body>"""


def unsubscribe_page(p, method):
    email = mailer.decode_unsub(p.get("e") or "", p.get("t") or "")
    if not email:
        return UNSUB_PAGE.format(title="This link isn't valid", body="Please reply to the email with the word "
                                 "\"unsubscribe\" and we'll remove you.")
    if method == "GET" and p.get("confirm") != "1":
        q = urlencode({"e": p["e"], "t": p["t"], "confirm": "1"})
        return UNSUB_PAGE.format(title="Unsubscribe?", body=f"Stop all emails to <b>{email}</b>?"
                                 f"<br><br><a href=\"?{q}\" style=\"background:#1f4fa3;color:#fff;padding:.6rem 1rem;"
                                 f"border-radius:6px;text-decoration:none\">Yes, unsubscribe me</a>")
    mailer.suppress(conn(), email, "unsubscribed")
    return UNSUB_PAGE.format(title="You're unsubscribed", body=f"We won't email <b>{email}</b> again. Sorry for "
                             "the bother, and thank you for the work you do.")


def run_cron():
    """One sending round plus one inbox check; for a scheduler hitting /api/cron."""
    c = conn()
    out = {"tick": mailer.tick(c)}
    if mailer.settings(c)["sending"]:
        out["inbox"] = mailer.check_next_inbox(c)
    return out


# ---------- HTTP ----------

COOKIE = "africa_session"


def auth_required():
    return bool(config.APP_PASSWORD) or config.ON_VERCEL


def _token():
    return hmac.new(config.SECRET_KEY.encode(), b"africa-schools/v1", hashlib.sha256).hexdigest()


def setup_problem():
    missing = []
    if config.ON_VERCEL and not config.APP_PASSWORD:
        missing.append("APP_PASSWORD")
    if config.ON_VERCEL and not (config.TURSO_URL and config.TURSO_TOKEN):
        missing += [k for k, v in (("TURSO_DATABASE_URL", config.TURSO_URL), ("TURSO_AUTH_TOKEN", config.TURSO_TOKEN))
                    if not v]
    return missing


class Handler(BaseHTTPRequestHandler):
    server_version = "AfricaSchools/1.0"

    def log_message(self, fmt, *args):
        first = str(args[0]) if args else ""
        if "/api/" in first and len(args) > 1 and not str(args[1]).startswith("2"):
            log("  " + fmt % args)

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        data = body if isinstance(body, bytes) else (
            body.encode() if isinstance(body, str) else json.dumps(body, default=str).encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        """The JSON body, read once: a second read would wait forever on a kept-alive connection."""
        if not hasattr(self, "_json"):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                self._json = json.loads(self.rfile.read(n)) if n else {}
            except ValueError:
                self._json = {}
        return self._json if isinstance(self._json, dict) else {}

    def _params(self):
        return {k: v[-1] for k, v in parse_qs(urlsplit(self.path).query).items()}

    def _authed(self):
        if not auth_required():
            return True
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE and hmac.compare_digest(v, _token()):
                return True
        return False

    def _login(self, method):
        if method != "POST":
            return self._send(405, {"error": "method"})
        pw = str(self._body().get("password") or "")
        if not config.APP_PASSWORD or not hmac.compare_digest(pw.encode(), config.APP_PASSWORD.encode()):
            time.sleep(0.8)
            return self._send(401, {"error": "That password isn't right."})
        secure = "; Secure" if config.ON_VERCEL else ""
        return self._send(200, {"ok": True}, headers={
            "Set-Cookie": f"{COOKIE}={_token()}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000{secure}"})

    def _route(self, method):
        parts = urlsplit(self.path)
        path = parts.path
        q = parse_qs(parts.query)
        if "__p" in q:  # Vercel rewrites /api/* to /api/index?__p=<rest>
            rest = q.pop("__p")[-1]
            path = "/api/" + rest.lstrip("/")
            self.path = path + ("?" + urlencode({k: v[-1] for k, v in q.items()}) if q else "")
        try:
            if path.startswith("/api/"):
                sub = path[5:]
                if sub == "me":
                    return self._send(200, {"auth": auth_required(), "signed_in": self._authed(),
                                            "missing": setup_problem()})
                if sub == "login":
                    return self._login(method)
                if sub == "logout":
                    return self._send(200, {"ok": True}, headers={"Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0"})
                if sub == "u":  # unsubscribe links work without signing in
                    return self._send(200, unsubscribe_page(self._params(), method), "text/html; charset=utf-8")
                if sub == "cron":
                    auth = self.headers.get("Authorization") or ""
                    if not config.CRON_SECRET or not hmac.compare_digest(auth, f"Bearer {config.CRON_SECRET}"):
                        return self._send(401, {"error": "Set CRON_SECRET and send it as a Bearer token."})
                    return self._send(200, run_cron())
                missing = setup_problem()
                if missing:
                    return self._send(503, {"error": "not_configured", "missing": missing})
                if not self._authed():
                    return self._send(401, {"error": "sign_in"})
                return self._api(method, sub)
            if method != "GET":
                return self._send(405, {"error": "method"})
            return self._static(path)
        except db.WrongDatabase as e:
            return self._send(503, {"error": str(e), "missing": ["a new database for the Africa CRM"]})
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": str(e)})

    def _api(self, method, path):
        p = self._params()
        get_ = method == "GET"
        c = conn()
        country = (p.get("country") or "").upper()
        one = country if country in COUNTRIES else None
        simple = {
            ("GET", "countries"): lambda: public_countries(),
            ("GET", "summary"): lambda: api_summary(one),
            ("GET", "facets"): lambda: api_facets(one),
            ("GET", "schools"): lambda: api_schools(p),
            ("GET", "pipeline"): lambda: api_pipeline(p),
            ("GET", "accounts"): lambda: api_accounts(),
            ("GET", "outreach"): lambda: api_outreach(one),
            ("GET", "replies"): lambda: api_replies(p),
            ("GET", "whatsapp/queue"): lambda: phone.queue(c, *build_filter(p), limit=min(int(p.get("limit") or 25), 100)),
            ("GET", "suppressions"): lambda: {"rows": [dict(r) for r in c.execute(
                "SELECT * FROM suppressions ORDER BY created_at DESC LIMIT 500")]},
        }
        if (method, path) in simple:
            return self._send(200, simple[(method, path)]())
        if get_ and path == "export.csv":
            name = (get(one).slug if one else "africa") + "-schools.csv"
            return self._send(200, api_export(p), "text/csv; charset=utf-8",
                              {"Content-Disposition": f'attachment; filename="{name}"'})
        if method == "POST":
            body = self._body()
            posts = {"bulk": api_bulk, "accounts": api_create_account, "enroll": api_enroll, "preview": api_preview,
                     "suppressions": api_suppress, "settings": api_settings, "enrollments/bulk": api_bulk_enrollments}
            if path in posts:
                return self._send(200, posts[path](body))
            if path == "sending":
                db.set_meta(c, "sending", "1" if body.get("on") else "0")
                return self._send(200, api_outreach(one))
            if path == "send/tick":
                return self._send(200, mailer.tick(c))
            if path == "replies/check-next":
                return self._send(200, mailer.check_next_inbox(c, max_age=float(body.get("max_age", 900))))
        m = re.fullmatch(r"templates/(\w+)(?:/(\d))?", path)
        if m and method in ("PUT", "PATCH", "POST", "DELETE"):
            return self._send(200, api_templates(method, m.group(1), int(m.group(2)) if m.group(2) else None,
                                                 self._body()))
        m = re.fullmatch(r"accounts/(\d+)(?:/([\w-]+))?", path)
        if m:
            aid, action = int(m.group(1)), m.group(2)
            acc = c.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
            if not acc:
                return self._send(404, {"error": "not found"})
            if method == "PATCH" and not action:
                return self._send(200, api_patch_account(aid, self._body()))
            if method == "DELETE" and not action:
                return self._send(200, api_delete_account(aid, self._body()))
            if method == "POST" and action == "test":
                return self._send(200, mailer.test_login(acc))
            if method == "POST" and action == "check-replies":
                try:
                    return self._send(200, mailer.check_replies(c, acc))
                except Exception as e:
                    return self._send(200, {"error": f"{type(e).__name__}: {e}"})
        m = re.fullmatch(r"enrollments/(\d+)", path)
        if m and method == "POST":
            r = api_enrollment_action(int(m.group(1)), self._body())
            return self._send(200 if r else 404, r or {"error": "not found"})
        m = re.fullmatch(r"suppressions/(.+)", path)
        if m and method == "DELETE":
            c.execute("DELETE FROM suppressions WHERE email=?", (m.group(1).lower(),))
            c.commit()
            return self._send(200, {"ok": True})
        m = re.fullmatch(r"whatsapp/(\d+)", path)
        if m and method in ("POST", "DELETE"):
            sid = int(m.group(1))
            if method == "DELETE":
                phone.reset(c, sid)
                return self._send(200, {"ok": True})
            b = self._body()
            r = phone.record(c, sid, b.get("outcome"), b.get("number"), b.get("note"))
            return self._send(200 if r else 404, r or {"error": "not found"})
        m = re.fullmatch(r"schools/(\d+)(?:/(\w+))?", path)
        if m:
            sid, action = int(m.group(1)), m.group(2)
            if get_ and not action:
                s = api_school(sid)
                return self._send(200 if s else 404, s or {"error": "not found"})
            if method == "PATCH" and not action:
                s = api_patch_school(sid, self._body())
                return self._send(200 if s else 404, s or {"error": "not found"})
            if method == "POST" and action == "activities":
                return self._send(200, api_activity(sid, self._body()))
            if method == "POST" and action == "contacts":
                s = api_add_contact(sid, self._body())
                return self._send(200 if s else 404, s or {"error": "not found"})
        m = re.fullmatch(r"contacts/(\d+)", path)
        if m and method == "PATCH":
            s = api_patch_contact(int(m.group(1)), self._body())
            return self._send(200 if s else 404, s or {"error": "not found"})
        return self._send(404, {"error": "no such endpoint"})

    def _static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        target = (config.UI_DIR / path.lstrip("/")).resolve()
        if not str(target).startswith(str(config.UI_DIR.resolve())) or not target.is_file():
            target = config.UI_DIR / "index.html"
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def do_GET(self):
        self._route("GET")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_POST(self):
        self._route("POST")

    def do_PATCH(self):
        self._route("PATCH")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")


def _background_sender(stop):
    """While the local server runs: one tick every 20 s, and an inbox check every 15 minutes per account."""
    c = db.connect()
    while not stop.wait(20):
        try:
            res = mailer.tick(c)
            for a in res.get("accounts", []):
                if str(a.get("status", "")).startswith(("sent", "send failed", "address refused", "sign-in")):
                    log(f"  [{a['label']}] {a['status']}")
            if mailer.settings(c)["sending"]:
                r = mailer.check_next_inbox(c)
                if r.get("error"):
                    log(f"  [{r['account']}] inbox check failed: {r['error']}")
        except Exception:
            traceback.print_exc()


def serve(host="127.0.0.1", port=8150):
    if host not in ("127.0.0.1", "localhost") and not config.APP_PASSWORD:
        raise SystemExit("Set APP_PASSWORD before serving the CRM beyond this computer.")
    db.connect().close()
    stop = threading.Event()
    threading.Thread(target=_background_sender, args=(stop,), daemon=True).start()
    httpd = ThreadingHTTPServer((host, port), Handler)
    log(f"Africa Schools CRM running at http://{host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
