"""WhatsApp and text-message outreach, done by a person from their own phone.

Most African schools publish a phone number but no email. The CRM never sends WhatsApp
messages itself: it lines schools up one at a time with the message already written, you
press "Open WhatsApp", send it from your own WhatsApp (app or WhatsApp Web), and record what
happened. That keeps it inside WhatsApp's rules for personal and Business-app accounts. See
README.md, "WhatsApp", for the WhatsApp Business Platform (API) option.
"""

import time
from urllib.parse import quote

from . import db, mailer
from .countries import get

OUTCOMES = {
    "sent": "WhatsApp message sent",
    "sms": "Text message sent",
    "replied": "Replied on WhatsApp",
    "not_on_whatsapp": "Number isn't on WhatsApp",
    "wrong_number": "Wrong number",
    "skipped": "Skipped for now",
}
DAY = 86400


def links(school, number, msgs):
    digits = "".join(ch for ch in number if ch.isdigit())
    return {"whatsapp": f"https://wa.me/{digits}?text={quote(msgs['whatsapp'])}",
            "sms": f"sms:+{digits}?&body={quote(msgs['sms'])}", "tel": f"tel:+{digits}"}


def queue_sql(where):
    """Schools with a mobile number that haven't been messaged yet and haven't said no."""
    extra = ("s.mobile IS NOT NULL AND s.whatsapp_status IS NULL AND "
             "s.status NOT IN ('do_not_contact','not_interested','partner')")
    return (where + " AND " if where else "WHERE ") + extra


def queue(conn, where, params, limit=25):
    w = queue_sql(where)
    total = conn.execute(f"SELECT COUNT(*) FROM schools s {w}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT s.* FROM schools s {w} ORDER BY (s.leader IS NOT NULL) DESC, (s.status='replied') DESC, "
        f"s.country, s.district, s.name LIMIT ?", params + [limit]).fetchall()
    s = mailer.settings(conn)
    out = []
    for r in rows:
        msgs = mailer.phone_messages(conn, r, s)
        out.append({"id": r["id"], "country": r["country"], "name": r["name"], "district": r["district"],
                    "town": r["town"], "leader": r["leader"], "number": r["mobile"], "email": r["email"],
                    "status": r["status"], "messages": msgs, "links": links(r, r["mobile"], msgs)})
    return {"total": total, "rows": out, "today": today(conn), "target": s["whatsapp_daily_target"]}


def today(conn, t=None):
    t = t or time.time()
    return conn.execute("SELECT COUNT(*) FROM activities WHERE kind IN ('whatsapp','sms') AND created_at>=? "
                        "AND body LIKE '%sent%'", (t - (t % DAY),)).fetchone()[0]


def record(conn, school_id, outcome, number=None, note=None):
    if outcome not in OUTCOMES:
        raise ValueError("Unknown outcome.")
    r = conn.execute("SELECT * FROM schools WHERE id=?", (school_id,)).fetchone()
    if not r:
        return None
    t = db.now()
    number = number or r["mobile"] or r["phone"] or ""
    body = OUTCOMES[outcome] + (f" ({number})" if number else "") + (f": {note}" if note else "")
    db.log_activity(conn, school_id, "sms" if outcome == "sms" else "whatsapp", body, t)
    status = {"sms": "sent"}.get(outcome, outcome)
    conn.execute("UPDATE schools SET whatsapp_status=?, whatsapp_at=?, updated_at=? WHERE id=?",
                 (status, t, t, school_id))
    if outcome in ("sent", "sms") and db.STATUS_RANK.get(r["status"], 0) < db.STATUS_RANK["contacted"]:
        conn.execute("UPDATE schools SET status='contacted' WHERE id=?", (school_id,))
    if outcome == "replied" and db.STATUS_RANK.get(r["status"], 0) < db.STATUS_RANK["replied"]:
        conn.execute("UPDATE schools SET status='replied' WHERE id=?", (school_id,))
    if outcome == "wrong_number" and number:
        conn.execute("UPDATE contacts SET active=0 WHERE school_id=? AND kind='phone' AND value=?",
                     (school_id, number))
        db.refresh_primary(conn, school_id, r["country"])
    conn.commit()
    return {"ok": True, "country": get(r["country"]).code}


def reset(conn, school_id):
    conn.execute("UPDATE schools SET whatsapp_status=NULL, whatsapp_at=NULL WHERE id=?", (school_id,))
    conn.commit()
