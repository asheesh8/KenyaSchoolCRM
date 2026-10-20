"""The CRM: a JSON API over the SQLite directory, the sender accounts and the email queue,
plus the static UI in ui/."""

import csv
import hashlib
import hmac
import io
import json
import mimetypes
import re
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from . import config, db, levels, mailer
from .net import log

_local = threading.local()


def conn():
    c = getattr(_local, "conn", None)
    if c is None:
        c = _local.conn = db.connect()
    return c


SORTS = {
    "best": ["(s.email IS NOT NULL) DESC", "(s.leader IS NOT NULL) DESC", "(s.phone IS NOT NULL) DESC",
             "CASE s.confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END", "s.name COLLATE NOCASE"],
    "name": ["s.name COLLATE NOCASE {dir}"],
    "district": ["s.district {dir}", "s.name COLLATE NOCASE"],
    "status": ["s.status {dir}", "s.name COLLATE NOCASE"],
    "touched": ["s.touched_at {dir} NULLS LAST"],
}
LIST_COLS = """s.id, s.name, s.kind, s.levels, s.ownership, s.denomination, s.district, s.province, s.chiefdom,
    s.town, s.lat, s.lon, s.emis_code, s.students, s.email, s.phone, s.website, s.leader, s.confidence, s.status, s.starred,
    s.tags, s.touched_at,
    (SELECT COUNT(*) FROM contacts k WHERE k.school_id=s.id AND k.kind='email' AND k.active=1) AS n_emails,
    (SELECT e.status || ':' || e.next_step FROM enrollments e WHERE e.school_id=s.id
       ORDER BY e.updated_at DESC LIMIT 1) AS sequence"""


def build_filter(p):
    where, params = [], []

    def multi(key):
        v = p.get(key)
        return [x for x in str(v).split(",") if x] if v else []

    q = (p.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        where.append("(s.name LIKE ? OR s.town LIKE ? OR s.chiefdom LIKE ? OR s.leader LIKE ? OR s.email LIKE ? "
                     "OR s.emis_code LIKE ? OR EXISTS (SELECT 1 FROM contacts k WHERE k.school_id=s.id AND "
                     "k.value LIKE ?))")
        params += [like] * 7
    for key, col in (("district", "s.district"), ("province", "s.province"), ("status", "s.status"),
                     ("ownership", "s.ownership"), ("denomination", "s.denomination"), ("kind", "s.kind"),
                     ("confidence", "s.confidence")):
        vals = multi(key)
        if vals:
            named = [v for v in vals if v != "none"]
            parts = ([f"{col} IN ({','.join('?' * len(named))})"] if named else []) + \
                    ([f"{col} IS NULL"] if "none" in vals else [])
            where.append("(" + " OR ".join(parts) + ")")
            params += named
    lv = multi("level")
    if lv:
        m = levels.mask(lv)
        where.append(f"(s.levels & {m}" + (" OR s.levels = 0)" if "unknown" in lv else ")"))
    for h in multi("has"):
        if h in ("email", "phone", "website", "leader", "emis_code"):
            where.append(f"s.{h} IS NOT NULL")
    for h in multi("missing"):
        if h in ("email", "phone", "website", "leader"):
            where.append(f"s.{h} IS NULL")
    seq = p.get("sequence")
    if seq == "none":
        where.append("NOT EXISTS (SELECT 1 FROM enrollments e WHERE e.school_id=s.id)")
    elif seq:
        where.append("EXISTS (SELECT 1 FROM enrollments e WHERE e.school_id=s.id AND e.status=?)")
        params.append(seq)
    if p.get("starred") == "1":
        where.append("s.starred=1")
    if p.get("tag"):
        where.append("EXISTS (SELECT 1 FROM json_each(s.tags) WHERE json_each.value=?)")
        params.append(p["tag"])
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
    total = c.execute(f"SELECT COUNT(*) FROM schools s {where}", params).fetchone()[0]
    rows = c.execute(f"SELECT {LIST_COLS} FROM schools s {where} ORDER BY {order} LIMIT ? OFFSET ?",
                     params + [per, (page - 1) * per]).fetchall()
    with_email = c.execute(f"SELECT COUNT(*) FROM schools s {where} {'AND' if where else 'WHERE'} s.email IS NOT NULL",
                           params).fetchone()[0]
    return {"total": total, "with_email": with_email, "page": page, "per": per, "rows": [_row(r) for r in rows]}


def matching_ids(p):
    where, params = build_filter(p)
    return [r[0] for r in conn().execute(f"SELECT s.id FROM schools s {where}", params).fetchall()]


def api_school(sid):
    c = conn()
    r = c.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    if not r:
        return None
    d = _row(r)
    d["contacts"] = [dict(x) for x in c.execute(
        "SELECT * FROM contacts WHERE school_id=? ORDER BY active DESC, kind, "
        "CASE confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END", (sid,))]
    d["activities"] = [dict(x) for x in c.execute(
        "SELECT * FROM activities WHERE school_id=? ORDER BY created_at DESC LIMIT 100", (sid,))]
    d["enrollments"] = [dict(x) for x in c.execute(
        "SELECT e.*, a.label AS account_label FROM enrollments e LEFT JOIN accounts a ON a.id=e.account_id "
        "WHERE e.school_id=?", (sid,))]
    sup = {x[0] for x in c.execute("SELECT email FROM suppressions")}
    for k in d["contacts"]:
        k["suppressed"] = k["kind"] == "email" and k["value"] in sup
    d["phone_messages"] = mailer.phone_messages(c, r)
    return d


def api_patch_school(sid, body):
    c = conn()
    r = c.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    if not r:
        return None
    if "status" in body and body["status"] in db.STATUSES and body["status"] != r["status"]:
        c.execute("UPDATE schools SET status=? WHERE id=?", (body["status"], sid))
        db.log_activity(c, sid, "status", f"Stage: {r['status']} → {body['status']}")
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
    kind = body.get("kind") if body.get("kind") in ("note", "call", "email", "meeting", "visit") else "note"
    c = conn()
    db.log_activity(c, sid, kind, str(body.get("body") or "")[:5000])
    c.commit()
    return api_school(sid)


def api_add_contact(sid, body):
    kind = body.get("kind")
    value = str(body.get("value") or "").strip()
    if kind == "email":
        value = levels.clean_email(value)
    elif kind == "phone":
        value = levels.clean_phone(value) or value
    if kind not in ("email", "phone", "website", "person") or not value:
        return {"error": "Check the value."}
    c = conn()
    db.upsert_contact(c, sid, kind, value, "manual", body.get("person") or (value if kind == "person" else None),
                      body.get("role"), body.get("source_url"), "high")
    db.refresh_primary(c, sid)
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


def api_summary():
    c = conn()
    q = lambda sql, *a: c.execute(sql, a).fetchone()[0]  # noqa: E731
    by_district = []
    for d, (prov, census) in levels.DISTRICTS.items():
        n = q("SELECT COUNT(*) FROM schools WHERE district=? AND kind='school'", d)
        by_district.append({"district": d, "province": prov, "census": census, "schools": n,
                            "with_email": q("SELECT COUNT(*) FROM schools WHERE district=? AND email IS NOT NULL", d),
                            "contacted": q("SELECT COUNT(*) FROM schools WHERE district=? AND status NOT IN "
                                           "('new','queued')", d)})
    by_level = [{"key": k, "label": lbl, "short": short,
                 "schools": q(f"SELECT COUNT(*) FROM schools WHERE levels & {b}"),
                 "with_email": q(f"SELECT COUNT(*) FROM schools WHERE levels & {b} AND email IS NOT NULL"),
                 "census": levels.CENSUS_BY_LEVEL.get(k)} for k, b, lbl, short in levels.LEVELS]
    return {
        "total": q("SELECT COUNT(*) FROM schools"),
        "schools": q("SELECT COUNT(*) FROM schools WHERE kind='school'"),
        "offices": q("SELECT COUNT(*) FROM schools WHERE kind!='school'"),
        "census_total": levels.CENSUS_TOTAL,
        "with_email": q("SELECT COUNT(*) FROM schools WHERE email IS NOT NULL"),
        "unique_emails": q("SELECT COUNT(DISTINCT value) FROM contacts WHERE kind='email' AND active=1"),
        "with_phone": q("SELECT COUNT(*) FROM schools WHERE phone IS NOT NULL"),
        "with_leader": q("SELECT COUNT(*) FROM schools WHERE leader IS NOT NULL"),
        "email_confidence": {r[0] or "unknown": r[1] for r in c.execute(
            "SELECT confidence, COUNT(*) FROM contacts WHERE kind='email' AND active=1 GROUP BY confidence")},
        "statuses": {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM schools GROUP BY status")},
        "ownership": {r[0] or "unknown": r[1] for r in c.execute(
            "SELECT ownership, COUNT(*) FROM schools GROUP BY ownership")},
        "by_level": by_level, "by_district": by_district,
        "sequence": {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM enrollments GROUP BY status")},
        "sent_total": q("SELECT COUNT(*) FROM messages WHERE status='sent'"),
        "recent": [dict(r) for r in c.execute(
            "SELECT a.*, s.name FROM activities a JOIN schools s ON s.id=a.school_id ORDER BY a.created_at DESC LIMIT 12")],
    }


def api_facets():
    c = conn()
    return {
        "districts": [{"value": d, "province": p} for d, (p, _) in levels.DISTRICTS.items()],
        "provinces": levels.PROVINCES,
        "levels": [{"value": k, "label": lbl, "short": s} for k, _, lbl, s in levels.LEVELS],
        "denominations": [r[0] for r in c.execute(
            "SELECT denomination FROM schools WHERE denomination IS NOT NULL GROUP BY denomination "
            "ORDER BY COUNT(*) DESC")],
        "statuses": db.STATUSES,
        "tags": sorted({t for r in c.execute("SELECT tags FROM schools WHERE tags!='[]'") for t in json.loads(r[0])}),
    }


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
    w.writerow(["Name", "Type", "Levels", "District", "Province", "Chiefdom", "Town", "Ownership", "Denomination",
                "EMIS code", "Best email", "Email confidence", "All emails", "Phones", "Head / official", "Website",
                "Stage", "Sources"])
    for r in c.execute(f"SELECT s.* FROM schools s {where} ORDER BY s.district, s.name", params):
        cs = c.execute("SELECT kind, value FROM contacts WHERE school_id=? AND active=1", (r["id"],)).fetchall()
        w.writerow([r["name"], r["kind"], ", ".join(levels.SHORT[k] for k in levels.keys(r["levels"])), r["district"],
                    r["province"], r["chiefdom"], r["town"], r["ownership"], r["denomination"], r["emis_code"],
                    r["email"], r["confidence"], "; ".join(x["value"] for x in cs if x["kind"] == "email"),
                    "; ".join(x["value"] for x in cs if x["kind"] == "phone"), r["leader"], r["website"], r["status"],
                    " ".join(json.loads(r["sources"]))])
    return "﻿" + buf.getvalue()


# ---------- email ----------

ACCOUNT_FIELDS = {"label": str, "from_name": str, "from_email": str, "reply_to": str, "provider": str,
                  "smtp_host": str, "smtp_port": int, "smtp_security": str, "imap_host": str, "imap_port": int,
                  "username": str, "daily_cap": int, "hourly_cap": int, "min_gap_s": int, "warmup": int,
                  "warmup_start": int, "warmup_step": int, "window_start": int, "window_end": int, "signature": str,
                  "enabled": int}
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
        d.update(info, ready=ok, state=reason,
                 active=c.execute("SELECT COUNT(*) FROM enrollments WHERE account_id=? AND status='active'",
                                  (a["id"],)).fetchone()[0],
                 due=c.execute("SELECT COUNT(*) FROM enrollments WHERE account_id=? AND status='active' AND "
                               "next_due_at<=?", (a["id"], time.time())).fetchone()[0])
        out.append(d)
    return {"accounts": out, "max": config.MAX_ACCOUNTS,
            "presets": {k: {kk: vv for kk, vv in v.items()} for k, v in mailer.PRESETS.items()}}


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


def api_outreach():
    c = conn()
    s = mailer.settings(c)
    return {
        "settings": s, "public_url": config.PUBLIC_URL, "on_vercel": config.ON_VERCEL,
        "accounts": api_accounts()["accounts"],
        "sequence": {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM enrollments GROUP BY status")},
        "by_step": {r[0]: r[1] for r in c.execute(
            "SELECT next_step, COUNT(*) FROM enrollments WHERE status='active' GROUP BY next_step")},
        "sent_by_step": {r[0]: r[1] for r in c.execute(
            "SELECT step, COUNT(*) FROM messages WHERE status='sent' GROUP BY step")},
        "suppressed": c.execute("SELECT COUNT(*) FROM suppressions").fetchone()[0],
        "recent": [dict(r) for r in c.execute(
            "SELECT m.*, s.name AS school, a.label AS account FROM messages m LEFT JOIN schools s ON s.id=m.school_id "
            "LEFT JOIN accounts a ON a.id=m.account_id ORDER BY m.created_at DESC LIMIT 40")],
        "upcoming": [dict(r) for r in c.execute(
            "SELECT e.*, s.name AS school, a.label AS account FROM enrollments e JOIN schools s ON s.id=e.school_id "
            "LEFT JOIN accounts a ON a.id=e.account_id WHERE e.status='active' ORDER BY e.next_due_at LIMIT 40")],
        "templates": [dict(r) for r in c.execute("SELECT * FROM templates ORDER BY step")],
    }


def api_enroll(body):
    c = conn()
    ids = [int(i) for i in body.get("ids") or []]
    if body.get("filter") is not None:
        ids = matching_ids(body["filter"])
    if body.get("dry_run"):
        n_email = sum(1 for i in ids if c.execute("SELECT email FROM schools WHERE id=?", (i,)).fetchone()[0])
        return {"schools": len(ids), "with_email": n_email}
    acc = body.get("account_id") or None
    stats = mailer.enroll(c, ids, acc, body.get("mode") or "best")
    stats["schools"] = len(ids)
    return stats


def api_preview(body):
    c = conn()
    sid = int(body.get("school_id") or 0)
    s = c.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone() if sid else \
        c.execute("SELECT * FROM schools WHERE email IS NOT NULL ORDER BY (leader IS NOT NULL) DESC LIMIT 1").fetchone()
    acc = c.execute("SELECT * FROM accounts WHERE id=?", (body.get("account_id") or 0,)).fetchone() or \
        c.execute("SELECT * FROM accounts ORDER BY id LIMIT 1").fetchone()
    if not s:
        return {"error": "No school to preview with yet."}
    acc = acc or {"from_name": "Your name", "label": "Your name", "signature": "", "from_email": "you@example.org",
                  "reply_to": None}
    p = c.execute("SELECT value, role FROM contacts WHERE school_id=? AND kind='person' AND active=1 LIMIT 1",
                  (s["id"],)).fetchone()
    enr = {"person": p["value"] if p else None, "role": p["role"] if p else None, "email": s["email"] or "",
           "thread_subject": None}
    out = []
    for step in (1, 2, 3):
        subj, body_ = mailer.compose(c, acc, s, enr, step)
        if step == 1:
            enr["thread_subject"] = subj
        out.append({"step": step, "subject": subj, "body": body_})
    return {"school": s["name"], "to": s["email"], "emails": out}


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
        mailer.classify_inbound(c, e["email"], "manual", "")
    elif act == "unsubscribe":
        mailer.suppress(c, e["email"], "manual")
    elif act == "move" and body.get("account_id"):
        c.execute("UPDATE enrollments SET account_id=?, updated_at=? WHERE id=?", (int(body["account_id"]), db.now(), eid))
    elif act == "remove":
        c.execute("DELETE FROM enrollments WHERE id=?", (eid,))
    c.commit()
    return {"ok": True}


def api_suppress(body):
    c = conn()
    n = 0
    for e in re.split(r"[\s,;]+", str(body.get("emails") or "")):
        e = levels.clean_email(e)
        if e:
            mailer.suppress(c, e, body.get("reason") or "manual")
            n += 1
    return {"added": n}


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


# ---------- HTTP ----------

COOKIE = "sld_session"


def auth_required():
    return bool(config.APP_PASSWORD) or config.ON_VERCEL


def _token():
    return hmac.new(config.SECRET_KEY.encode(), b"sierra-leone-schools/v1", hashlib.sha256).hexdigest()


def setup_problem():
    missing = []
    if config.ON_VERCEL and not config.APP_PASSWORD:
        missing.append("APP_PASSWORD")
    if config.ON_VERCEL and not (config.TURSO_URL and config.TURSO_TOKEN):
        missing += [k for k, v in (("TURSO_DATABASE_URL", config.TURSO_URL), ("TURSO_AUTH_TOKEN", config.TURSO_TOKEN))
                    if not v]
    return missing


class Handler(BaseHTTPRequestHandler):
    server_version = "SierraLeoneSchools/1.0"

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
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except ValueError:
            return {}

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
                missing = setup_problem()
                if missing:
                    return self._send(503, {"error": "not_configured", "missing": missing})
                if not self._authed():
                    return self._send(401, {"error": "sign_in"})
                return self._api(method, sub)
            if method != "GET":
                return self._send(405, {"error": "method"})
            return self._static(path)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": str(e)})

    def _api(self, method, path):
        p = self._params()
        get = method == "GET"
        c = conn()
        simple = {
            ("GET", "summary"): lambda: api_summary(),
            ("GET", "facets"): lambda: api_facets(),
            ("GET", "schools"): lambda: api_schools(p),
            ("GET", "pipeline"): lambda: api_pipeline(p),
            ("GET", "accounts"): lambda: api_accounts(),
            ("GET", "outreach"): lambda: api_outreach(),
            ("GET", "suppressions"): lambda: {"rows": [dict(r) for r in c.execute(
                "SELECT * FROM suppressions ORDER BY created_at DESC LIMIT 500")]},
        }
        if (method, path) in simple:
            return self._send(200, simple[(method, path)]())
        if get and path == "export.csv":
            return self._send(200, api_export(p), "text/csv; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="sierra-leone-schools.csv"'})
        if method == "POST":
            body = self._body()
            posts = {"bulk": api_bulk, "accounts": api_create_account, "enroll": api_enroll, "preview": api_preview,
                     "suppressions": api_suppress}
            if path in posts:
                return self._send(200, posts[path](body))
            if path == "sending":
                db.set_meta(c, "sending", "1" if body.get("on") else "0")
                return self._send(200, api_outreach())
            if path == "send/tick":
                return self._send(200, mailer.tick(c))
            if path == "settings":
                for k in ("org_name", "library_link", "phone_sender"):
                    if k in body:
                        db.set_meta(c, k, str(body[k])[:500])
                for k in mailer.DEFAULT_PHONE_MESSAGES:
                    if k in body:
                        db.set_meta(c, k, str(body[k])[:2000])
                if "weekdays_only" in body:
                    db.set_meta(c, "weekdays_only", "1" if body["weekdays_only"] else "0")
                return self._send(200, api_outreach())
        m = re.fullmatch(r"templates/(\d)", path)
        if m and method in ("PUT", "PATCH"):
            b = self._body()
            c.execute("UPDATE templates SET name=COALESCE(?, name), subject=COALESCE(?, subject), "
                      "body=COALESCE(?, body), delay_days=COALESCE(?, delay_days) WHERE step=?",
                      (b.get("name"), b.get("subject"), b.get("body"),
                       max(0.0, float(b["delay_days"])) if b.get("delay_days") not in (None, "") else None,
                       int(m.group(1))))
            c.commit()
            return self._send(200, api_outreach())
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
        m = re.fullmatch(r"schools/(\d+)(?:/(\w+))?", path)
        if m:
            sid, action = int(m.group(1)), m.group(2)
            if get and not action:
                s = api_school(sid)
                return self._send(200 if s else 404, s or {"error": "not found"})
            if method == "PATCH" and not action:
                s = api_patch_school(sid, self._body())
                return self._send(200 if s else 404, s or {"error": "not found"})
            if method == "POST" and action == "activities":
                return self._send(200, api_activity(sid, self._body()))
            if method == "POST" and action == "contacts":
                return self._send(200, api_add_contact(sid, self._body()))
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
    """While the local server runs: one tick every 20 s, and an inbox check every 15 minutes."""
    c = db.connect()
    last_check = 0.0
    while not stop.wait(20):
        try:
            res = mailer.tick(c)
            for a in res.get("accounts", []):
                if str(a.get("status", "")).startswith(("sent", "send failed", "address refused", "sign-in")):
                    log(f"  [{a['label']}] {a['status']}")
            if mailer.settings(c)["sending"] and time.time() - last_check > 900:
                last_check = time.time()
                for acc in c.execute("SELECT * FROM accounts WHERE enabled=1 AND imap_host IS NOT NULL "
                                     "AND imap_host!=''").fetchall():
                    try:
                        mailer.check_replies(c, acc)
                    except Exception as e:
                        log(f"  [{acc['label']}] inbox check failed: {e}")
        except Exception:
            traceback.print_exc()


def serve(host="127.0.0.1", port=8140):
    if host not in ("127.0.0.1", "localhost") and not config.APP_PASSWORD:
        raise SystemExit("Set APP_PASSWORD before serving the CRM beyond this computer.")
    db.connect().close()
    stop = threading.Event()
    threading.Thread(target=_background_sender, args=(stop,), daemon=True).start()
    httpd = ThreadingHTTPServer((host, port), Handler)
    log(f"Sierra Leone Schools Directory running at http://{host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
