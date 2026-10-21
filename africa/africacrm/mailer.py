"""Sender accounts, the three-step sequence, rate limits, unsubscribes and reply checks.

The seven accounts are shared by every country. Nothing here sends on its own: mail goes
out only while sending is switched on (the Start button on the Email page, or
`python3 -m africacrm send`), and then at most one message per account per tick, inside
that account's limits:

  * a daily cap that ramps up from `warmup_start` by `warmup_step` a day for new mailboxes,
  * an hourly cap, and a minimum gap between messages with random jitter,
  * a sending window in each school's own local time (default 08:00-17:00, weekdays), so a
    Kampala school and a Freetown school are both emailed during their working day,
  * automatic pause after three failures in a row, or at once on a login error.

Suppressed addresses (unsubscribed, bounced, asked to stop) are never mailed again, in any country.
"""

import base64
import hashlib
import hmac
import imaplib
import os
import random
import re
import smtplib
import ssl
import time
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr

from . import config, db
from .countries import COUNTRIES, get

PRESETS = {
    "gmail": {"smtp_host": "smtp.gmail.com", "smtp_port": 587, "smtp_security": "starttls",
              "imap_host": "imap.gmail.com",
              "help": "Turn on 2-Step Verification, then create an App Password at myaccount.google.com/apppasswords "
                      "and paste it here (not your normal password)."},
    "workspace": {"smtp_host": "smtp.gmail.com", "smtp_port": 587, "smtp_security": "starttls",
                  "imap_host": "imap.gmail.com",
                  "help": "Google Workspace: same as Gmail. Your admin may need to allow App Passwords."},
    "outlook": {"smtp_host": "smtp.office365.com", "smtp_port": 587, "smtp_security": "starttls",
                "imap_host": "outlook.office365.com",
                "help": "Microsoft 365 / Outlook.com: SMTP AUTH must be enabled for the mailbox; use an app password "
                        "if the account has two-step sign-in."},
    "zoho": {"smtp_host": "smtp.zoho.com", "smtp_port": 465, "smtp_security": "ssl", "imap_host": "imap.zoho.com",
             "help": "Zoho Mail: create an application-specific password under Security."},
    "yahoo": {"smtp_host": "smtp.mail.yahoo.com", "smtp_port": 465, "smtp_security": "ssl",
              "imap_host": "imap.mail.yahoo.com",
              "help": "Yahoo: generate an app password under Account security."},
    "custom": {"smtp_host": "", "smtp_port": 587, "smtp_security": "starttls", "imap_host": "",
               "help": "Any mailbox that offers SMTP. Your host's settings page lists the server and port."},
}

DEFAULT_TEMPLATES = [
    {"step": 1, "name": "Introduction", "delay_days": 0,
     "subject": "A free Bible library for {{school}}",
     "body": """{{greeting}}

My name is {{sender_name}}, and I'm with {{org}}. We work with schools across {{country}} to give pupils and teachers free access to a library of Bibles and Bible-based reading materials.

I'd love to share it with {{school}}. Teachers use it in religious education lessons, morning devotion and assemblies, and in school fellowships and clubs. There is no cost to the school and nothing to sign.

Are you the right person to speak with about this? If not, could you point me to the best contact?

With thanks,
{{signature}}"""},
    {"step": 2, "name": "Library offer", "delay_days": 4, "subject": "",
     "body": """{{greeting}}

I'm following up on my note about the free library for {{school}}.

It includes Bibles and Bible-based readers, stories and study materials for different ages, which teachers can use in class, in devotion and in clubs. You can see what's included here: {{library_link}}

If it would be useful, just reply with roughly how many pupils and teachers you have, and we'll arrange access for your school.

Warm regards,
{{signature}}"""},
    {"step": 3, "name": "Follow-up", "delay_days": 7, "subject": "",
     "body": """{{greeting}}

I'm trying once more in case my earlier emails were missed. Our offer of a free Bible library for {{school}} still stands, and we're happy to work around your school calendar.

If someone else at the school looks after this, I'd be grateful if you could pass it on. And if now isn't a good time, just let me know and I won't write again.

Blessings,
{{signature}}"""},
]

# Most schools have a phone but no email: these open in WhatsApp or the phone's SMS app from the school panel.
DEFAULT_PHONE_MESSAGES = {
    "whatsapp_message": """{{hello}} my name is {{sender_name}} from {{org}}. We're giving schools in {{country}} a free library of Bibles and Bible-based reading materials for pupils and teachers, at no cost to the school.

I'd love to share it with {{school}}. You can see what's included here: {{library_link}}

Are you the right person to talk to about this? If not, who should I contact? Thank you, and God bless.""",
    "sms_message": "{{hello}} this is {{sender_name}} from {{org}}. We'd like to give {{school}} a free Bible library "
                   "for pupils and teachers. May I send you the details by WhatsApp or email? Reply STOP and we "
                   "won't contact you again.",
}

UNSUB_WORDS = re.compile(r"\b(unsubscribe|stop|remove me|take me off|do not (contact|email)|no more emails?)\b", re.I)
BOUNCE_FROM = re.compile(r"(mailer-daemon|postmaster|mail delivery)", re.I)


# ---------- secrets ----------

def _keys():
    k = hashlib.sha256(config.SECRET_KEY.encode()).digest()
    return hmac.new(k, b"enc", hashlib.sha256).digest(), hmac.new(k, b"mac", hashlib.sha256).digest()


def _stream(key, nonce, n):
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(key, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest()
        i += 1
    return out[:n]


def encrypt(plain):
    if not plain:
        return None
    ek, mk = _keys()
    nonce = os.urandom(16)
    data = plain.encode()
    ct = bytes(a ^ b for a, b in zip(data, _stream(ek, nonce, len(data))))
    tag = hmac.new(mk, nonce + ct, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(nonce + ct + tag).decode()


def decrypt(token):
    if not token:
        return None
    ek, mk = _keys()
    raw = base64.urlsafe_b64decode(token.encode())
    nonce, ct, tag = raw[:16], raw[16:-16], raw[-16:]
    if not hmac.compare_digest(tag, hmac.new(mk, nonce + ct, hashlib.sha256).digest()[:16]):
        return None  # SECRET_KEY changed since the password was saved
    return bytes(a ^ b for a, b in zip(ct, _stream(ek, nonce, len(ct)))).decode()


def account_password(acc):
    return os.environ.get(f"SENDER_{acc['id']}_PASSWORD") or decrypt(acc["password_enc"])


def public_account(acc):
    """An account as the browser may see it: never the password."""
    d = {k: acc[k] for k in acc.keys() if k not in ("password_enc", "lock_until")}
    d["has_password"] = bool(account_password(acc))
    d["password_from_env"] = bool(os.environ.get(f"SENDER_{acc['id']}_PASSWORD"))
    return d


# ---------- unsubscribe links ----------

def unsub_token(email):
    return hmac.new(config.SECRET_KEY.encode(), b"unsub:" + email.lower().encode(), hashlib.sha256).hexdigest()[:24]


def unsub_url(email):
    if not config.PUBLIC_URL:
        return None
    e = base64.urlsafe_b64encode(email.lower().encode()).decode().rstrip("=")
    return f"{config.PUBLIC_URL}/api/u?e={e}&t={unsub_token(email)}"


def decode_unsub(e, t):
    try:
        email = base64.urlsafe_b64decode((e + "=" * (-len(e) % 4)).encode()).decode()
    except Exception:
        return None
    return email if hmac.compare_digest(t or "", unsub_token(email)) else None


def suppress(conn, email, reason):
    email = email.lower().strip()
    conn.execute("INSERT INTO suppressions(email, reason, created_at) VALUES (?,?,?) ON CONFLICT(email) DO NOTHING",
                 (email, reason, db.now()))
    status = {"bounced": "bounced"}.get(reason, "unsubscribed")
    for e in conn.execute("SELECT id, school_id FROM enrollments WHERE email=?", (email,)).fetchall():
        conn.execute("UPDATE enrollments SET status=?, updated_at=? WHERE id=?", (status, db.now(), e["id"]))
        db.log_activity(conn, e["school_id"], "system", f"{email} {status.replace('_', ' ')} ({reason})")
    conn.commit()


def is_suppressed(conn, email):
    return bool(conn.execute("SELECT 1 FROM suppressions WHERE email=?", (email.lower(),)).fetchone())


# ---------- templates ----------

def settings(conn):
    s = {"org": db.get_meta(conn, "org_name", "") or "our ministry",
         "library_link": db.get_meta(conn, "library_link", "") or "",
         "weekdays_only": db.get_meta(conn, "weekdays_only", "1") == "1",
         "phone_sender": db.get_meta(conn, "phone_sender", "") or "",
         "whatsapp_daily_target": int(db.get_meta(conn, "whatsapp_daily_target", "40") or 40),
         **{k: db.get_meta(conn, k, "") or v for k, v in DEFAULT_PHONE_MESSAGES.items()},
         "sending": db.get_meta(conn, "sending", "0") == "1"}
    # A country can have its own WhatsApp / SMS wording ("whatsapp_message:UG").
    s["phone_overrides"] = {code: {k: db.get_meta(conn, f"{k}:{code}", "") or "" for k in DEFAULT_PHONE_MESSAGES}
                            for code in COUNTRIES}
    return s


def template(conn, country, step):
    """The country's own version of an email if it has one, else the shared one."""
    return conn.execute("SELECT * FROM templates WHERE step=? AND country IN (?, '') ORDER BY country DESC LIMIT 1",
                        (step, country or "")).fetchone()


def steps(conn, country=""):
    return sorted({r[0] for r in conn.execute("SELECT step FROM templates WHERE country IN (?, '')", (country,))})


def greeting(person, role):
    if person:
        parts = person.replace(",", " ").split()
        titles = {"mr", "mrs", "ms", "miss", "dr", "rev", "revd", "fr", "sr", "prof", "bishop", "pastor", "imam",
                  "sheikh", "alhaji", "hajia", "madam", "mr.", "mrs.", "ms.", "dr.", "rev.", "fr.", "prof."}
        if parts and parts[0].lower() in titles and len(parts) > 1:
            title = parts[0].rstrip(".").title().replace("Revd", "Rev")
            return f"Dear {title} {parts[-1]},"
        return f"Dear {person},"
    if role:
        return f"Dear {role},"
    return "Dear Sir or Madam,"


def render(text, ctx):
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(ctx.get(m.group(1), "") or ""), text or "")


def phone_messages(conn, school, s=None):
    """WhatsApp and SMS text for one school, addressed to its named head when there is one."""
    s = s or settings(conn)
    person = (school["leader"] or "").split(" (")[0]
    hello = greeting(person, None).replace("Dear ", "Good day ") if person else "Good day,"
    ctx = {"hello": hello, "school": school["name"], "person": person, "district": school["district"] or "",
           "town": school["town"] or "", "sender_name": s["phone_sender"] or "[your name]",
           "org": s["org"], "library_link": s["library_link"] or "[library link]",
           "country": get(school["country"]).name}
    own = s["phone_overrides"].get(school["country"], {})
    return {"whatsapp": render(own.get("whatsapp_message") or s["whatsapp_message"], ctx),
            "sms": render(own.get("sms_message") or s["sms_message"], ctx)}


def context(conn, acc, school, enr):
    s = settings(conn)
    sig = (acc["signature"] or "").strip() or "\n".join(x for x in (acc["from_name"], s["org"]) if x)
    return {"greeting": greeting(enr["person"], enr["role"]), "school": school["name"], "person": enr["person"] or "",
            "role": enr["role"] or "", "district": school["district"] or "", "town": school["town"] or "",
            "sender_name": acc["from_name"] or acc["label"], "org": s["org"], "library_link": s["library_link"],
            "signature": sig, "country": get(school["country"]).name}


def footer(school_name, email):
    url = unsub_url(email)
    line = ("You're receiving this because {school}'s contact details are published publicly. "
            "If you'd rather not hear from us, reply \"unsubscribe\"").format(school=school_name)
    return "\n\n--\n" + line + (f" or open {url}" if url else "") + " and we won't write again."


def compose(conn, acc, school, enr, step):
    t = template(conn, school["country"], step)
    ctx = context(conn, acc, school, enr)
    subject = render(t["subject"], ctx).strip()
    if not subject:
        base = enr["thread_subject"] or render(template(conn, school["country"], 1)["subject"], ctx)
        subject = base if base.lower().startswith("re:") else "Re: " + base
    body = render(t["body"], ctx).strip() + footer(school["name"], enr["email"])
    return subject, body


def build_message(acc, to_email, subject, body, thread_id=None):
    msg = EmailMessage()
    msg["From"] = formataddr((acc["from_name"] or "", acc["from_email"]))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=acc["from_email"].split("@")[-1])
    if acc["reply_to"]:
        msg["Reply-To"] = acc["reply_to"]
    if thread_id:
        msg["In-Reply-To"] = thread_id
        msg["References"] = thread_id
    unsub = [f"<mailto:{acc['reply_to'] or acc['from_email']}?subject=unsubscribe>"]
    url = unsub_url(to_email)
    if url:
        unsub.insert(0, f"<{url}>")
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg["List-Unsubscribe"] = ", ".join(unsub)
    msg.set_content(body)
    return msg


def _smtp(acc, timeout=30):
    ctx = ssl.create_default_context()
    if acc["smtp_security"] == "ssl":
        s = smtplib.SMTP_SSL(acc["smtp_host"], int(acc["smtp_port"]), timeout=timeout, context=ctx)
    else:
        s = smtplib.SMTP(acc["smtp_host"], int(acc["smtp_port"]), timeout=timeout)
        s.ehlo()
        if acc["smtp_security"] == "starttls":
            s.starttls(context=ctx)
            s.ehlo()
    s.login(acc["username"], account_password(acc) or "")
    return s


def smtp_send(acc, msg):
    with _smtp(acc) as s:
        s.send_message(msg)


def test_login(acc):
    """Signs in to SMTP (and IMAP when set) without sending anything."""
    out = {}
    try:
        with _smtp(acc):
            pass
        out["smtp"] = "ok"
    except Exception as e:
        out["smtp"] = f"{type(e).__name__}: {e}"
    if acc["imap_host"]:
        try:
            m = imaplib.IMAP4_SSL(acc["imap_host"], int(acc["imap_port"] or 993), ssl_context=ssl.create_default_context())
            m.login(acc["username"], account_password(acc) or "")
            m.logout()
            out["imap"] = "ok"
        except Exception as e:
            out["imap"] = f"{type(e).__name__}: {e}"
    return out


# ---------- limits ----------

DAY = 86400


def today_cap(acc, t):
    cap = int(acc["daily_cap"])
    if acc["warmup"]:
        days = int((t - acc["first_send_at"]) // DAY) if acc["first_send_at"] else 0
        cap = min(cap, int(acc["warmup_start"]) + int(acc["warmup_step"]) * days)
    return cap


def usage(conn, acc_id, t):
    day0 = t - (t % DAY)  # the daily cap resets at midnight GMT
    q = "SELECT COUNT(*) FROM messages WHERE account_id=? AND status='sent' AND created_at>=?"
    return conn.execute(q, (acc_id, day0)).fetchone()[0], conn.execute(q, (acc_id, t - 3600)).fetchone()[0]


def account_countries(acc):
    picked = [c.strip().upper() for c in (acc["countries"] or "").split(",") if c.strip().upper() in COUNTRIES]
    return picked or list(COUNTRIES)


def open_countries(acc, t, weekdays_only=True):
    """Countries where it is now inside this account's sending hours (local time, weekdays)."""
    out = []
    for code in account_countries(acc):
        lt = COUNTRIES[code].local_time(t)
        if weekdays_only and lt.weekday() >= 5:
            continue
        if int(acc["window_start"]) <= lt.hour < int(acc["window_end"]):
            out.append(code)
    return out


def allowance(conn, acc, t=None, weekdays_only=True):
    """(may_send_now, reason, details). details["countries"] lists where it's working hours now."""
    t = t or time.time()
    sent_day, sent_hour = usage(conn, acc["id"], t)
    cap = today_cap(acc, t)
    open_ = open_countries(acc, t, weekdays_only)
    info = {"sent_today": sent_day, "cap_today": cap, "sent_hour": sent_hour, "hourly_cap": acc["hourly_cap"],
            "open_countries": open_}
    if not acc["enabled"]:
        return False, "paused", info
    if not account_password(acc):
        return False, "no password saved", info
    if not open_:
        return False, (f"outside sending hours ({acc['window_start']}:00-{acc['window_end']}:00 local time"
                       + (", weekdays" if weekdays_only else "") + ")"), info
    if sent_day >= cap:
        return False, f"daily limit reached ({cap})", info
    if sent_hour >= int(acc["hourly_cap"]):
        return False, f"hourly limit reached ({acc['hourly_cap']})", info
    if acc["next_allowed_at"] and t < acc["next_allowed_at"]:
        return False, f"spacing messages (next in {int(acc['next_allowed_at'] - t)}s)", info
    return True, "ready", info


# ---------- enrolment ----------

def enroll(conn, school_ids, account_id=None, mode="best", t=None, campaign=None, spread_hours=0):
    """Put schools' emails into the sequence. account_id=None spreads them across enabled accounts
    (each school goes to the least-loaded account allowed to email its country).

    mode 'best' = the school's headline email only; 'all' = every email on the school record.
    Already-enrolled and suppressed addresses, and schools marked do-not-contact, are skipped.
    """
    t = t or db.now()
    rows = conn.execute("SELECT * FROM accounts WHERE enabled=1 ORDER BY id").fetchall()
    if account_id:
        rows = conn.execute("SELECT * FROM accounts WHERE id=?", (int(account_id),)).fetchall()
    if not rows:
        return {"error": "Connect a sender email account first."}
    allowed = {a["id"]: set(account_countries(a)) for a in rows}
    load = {a["id"]: conn.execute("SELECT COUNT(*) FROM enrollments WHERE account_id=? AND status='active'",
                                  (a["id"],)).fetchone()[0] for a in rows}
    stats = {"enrolled": 0, "already": 0, "suppressed": 0, "no_email": 0, "do_not_contact": 0, "no_account": 0}
    for sid in school_ids:
        s = conn.execute("SELECT * FROM schools WHERE id=?", (int(sid),)).fetchone()
        if not s:
            continue
        if s["status"] in ("do_not_contact", "not_interested"):
            stats["do_not_contact"] += 1
            continue
        rows = conn.execute("SELECT * FROM contacts WHERE school_id=? AND kind='email' AND active=1", (s["id"],)) \
            .fetchall()
        if mode != "all":
            rows = [r for r in rows if r["value"] == s["email"]] or rows[:1]
        if not rows:
            stats["no_email"] += 1
            continue
        for r in rows:
            email = r["value"].lower()
            if is_suppressed(conn, email):
                stats["suppressed"] += 1
                continue
            if conn.execute("SELECT 1 FROM enrollments WHERE email=?", (email,)).fetchone():
                stats["already"] += 1
                continue
            options = [a for a in load if s["country"] in allowed[a]]
            if not options:
                stats["no_account"] += 1
                continue
            acc = min(options, key=lambda a: (load[a], a))
            load[acc] += 1
            person, role = r["person"], r["role"]
            if not person:  # a school address: greet the head by name when the record has one
                p = conn.execute("SELECT value, role FROM contacts WHERE school_id=? AND kind='person' AND active=1 "
                                 "ORDER BY confidence='high' DESC LIMIT 1", (s["id"],)).fetchone()
                if p:
                    person, role = p["value"], p["role"]
            due = t + (random.uniform(0, spread_hours * 3600) if spread_hours else 0)
            conn.execute("INSERT INTO enrollments(school_id, country, campaign, email, person, role, account_id, "
                         "next_step, status, next_due_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,1,'active',?,?,?)",
                         (s["id"], s["country"], campaign, email, person, role, acc, due, t, t))
            stats["enrolled"] += 1
        if s["status"] == "new":
            conn.execute("UPDATE schools SET status='queued', updated_at=? WHERE id=?", (t, s["id"]))
    conn.commit()
    return stats


# ---------- sending ----------

def _claim(conn, acc_id, t):
    cur = conn.execute("UPDATE accounts SET lock_until=? WHERE id=? AND (lock_until IS NULL OR lock_until<?)",
                       (t + 90, acc_id, t))
    conn.commit()
    return cur.rowcount == 1


def _release(conn, acc_id):
    conn.execute("UPDATE accounts SET lock_until=NULL WHERE id=?", (acc_id,))
    conn.commit()


def tick(conn, send_fn=None, t=None, force=False):
    """Send at most one due message per account. Returns what happened per account.

    force=True ignores the global on/off switch (used by `send --once`), never the limits.
    """
    send_fn = send_fn or smtp_send
    t = t or time.time()
    s = settings(conn)
    out = []
    if not (s["sending"] or force):
        return {"sending": False, "accounts": out}
    for acc in conn.execute("SELECT * FROM accounts ORDER BY id").fetchall():
        res = {"account": acc["id"], "label": acc["label"]}
        out.append(res)
        ok, reason, info = allowance(conn, acc, t, s["weekdays_only"])
        res.update(info)
        if not ok:
            res["status"] = reason
            continue
        open_ = info["open_countries"]
        enr = conn.execute(
            f"SELECT * FROM enrollments WHERE account_id=? AND status='active' AND next_due_at<=? "
            f"AND country IN ({','.join('?' * len(open_))}) ORDER BY next_step DESC, next_due_at LIMIT 1",
            (acc["id"], t, *open_)).fetchone()
        if not enr:
            res["status"] = "nothing due" + ("" if len(open_) == len(account_countries(acc)) else
                                             f" in {', '.join(COUNTRIES[c].name for c in open_)} right now")
            continue
        if not _claim(conn, acc["id"], t):
            res["status"] = "busy"
            continue
        try:
            res.update(_send_one(conn, acc, enr, send_fn, t))
        finally:
            _release(conn, acc["id"])
    return {"sending": True, "accounts": out}


def _send_one(conn, acc, enr, send_fn, t):
    school = conn.execute("SELECT * FROM schools WHERE id=?", (enr["school_id"],)).fetchone()
    if not school or school["status"] in ("do_not_contact", "not_interested") or is_suppressed(conn, enr["email"]):
        conn.execute("UPDATE enrollments SET status='unsubscribed', updated_at=? WHERE id=?", (t, enr["id"]))
        conn.commit()
        return {"status": "skipped (do not contact)"}
    step = enr["next_step"]
    subject, body = compose(conn, acc, school, enr, step)
    msg = build_message(acc, enr["email"], subject, body, enr["thread_id"] if step > 1 else None)
    try:
        send_fn(acc, msg)
    except smtplib.SMTPRecipientsRefused as e:
        conn.execute("INSERT INTO messages(enrollment_id, school_id, account_id, country, to_email, step, subject, "
                     "status, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (enr["id"], school["id"], acc["id"], enr["country"], enr["email"], step, subject, "failed", str(e)[:300], t))
        suppress(conn, enr["email"], "bounced")
        return {"status": f"address refused: {enr['email']}"}
    except smtplib.SMTPAuthenticationError as e:
        conn.execute("UPDATE accounts SET enabled=0, last_error=? WHERE id=?",
                     (f"Sign-in failed, account paused: {e}"[:300], acc["id"]))
        conn.commit()
        return {"status": "sign-in failed; account paused"}
    except Exception as e:
        streak = (acc["fail_streak"] or 0) + 1
        conn.execute("INSERT INTO messages(enrollment_id, school_id, account_id, country, to_email, step, subject, "
                     "status, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (enr["id"], school["id"], acc["id"], enr["country"], enr["email"], step, subject, "failed",
                      f"{type(e).__name__}: {e}"[:300], t))
        conn.execute("UPDATE accounts SET fail_streak=?, last_error=?, enabled=CASE WHEN ?>=3 THEN 0 ELSE enabled END,"
                     " next_allowed_at=? WHERE id=?",
                     (streak, f"{type(e).__name__}: {e}"[:300], streak, t + 600, acc["id"]))
        conn.commit()
        return {"status": "send failed" + ("; account paused after 3 failures" if streak >= 3 else "")}
    gap = int(acc["min_gap_s"]) * random.uniform(1.0, 1.6)
    conn.execute("INSERT INTO messages(enrollment_id, school_id, account_id, country, to_email, step, subject, "
                 "status, message_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (enr["id"], school["id"], acc["id"], enr["country"], enr["email"], step, subject, "sent",
                  msg["Message-ID"], t))
    conn.execute("UPDATE accounts SET last_sent_at=?, next_allowed_at=?, fail_streak=0, last_error=NULL, "
                 "first_send_at=COALESCE(first_send_at, ?) WHERE id=?", (t, t + gap, t, acc["id"]))
    nxt = template(conn, school["country"], step + 1)
    if nxt:
        conn.execute("UPDATE enrollments SET next_step=?, next_due_at=?, thread_id=COALESCE(thread_id, ?), "
                     "thread_subject=COALESCE(thread_subject, ?), updated_at=? WHERE id=?",
                     (step + 1, t + float(nxt["delay_days"]) * DAY, msg["Message-ID"], subject, t, enr["id"]))
    else:
        conn.execute("UPDATE enrollments SET status='done', next_step=?, updated_at=? WHERE id=?",
                     (step + 1, t, enr["id"]))
    name = template(conn, school["country"], step)["name"]
    db.log_activity(conn, school["id"], "email", f"Email {step} ({name}) sent to {enr['email']} from {acc['label']}")
    if db.STATUS_RANK.get(school["status"], 0) < db.STATUS_RANK["contacted"]:
        conn.execute("UPDATE schools SET status='contacted', updated_at=? WHERE id=?", (t, school["id"]))
    conn.commit()
    return {"status": f"sent email {step} to {enr['email']}"}


# ---------- replies, stop requests and bounces ----------

def _text_of(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")
    except Exception:
        return str(msg.get_payload())


def classify_inbound(conn, from_addr, subject, text):
    """Apply one inbound message. Returns what it did, or None when it isn't about an enrolment."""
    from_addr = (from_addr or "").lower()
    if BOUNCE_FROM.search(from_addr) or BOUNCE_FROM.search(subject or ""):
        hits = set(re.findall(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text or ""))
        done = []
        for h in hits:
            if conn.execute("SELECT 1 FROM enrollments WHERE email=? AND status NOT IN ('bounced')",
                            (h.lower(),)).fetchone():
                suppress(conn, h, "bounced")
                done.append(h.lower())
        return ("bounced", done) if done else None
    enr = conn.execute("SELECT * FROM enrollments WHERE email=?", (from_addr,)).fetchone()
    if not enr or enr["status"] in ("replied", "unsubscribed", "bounced"):
        return None
    first = "\n".join(line for line in (text or "").splitlines()[:15] if not line.startswith(">"))
    if UNSUB_WORDS.search(subject or "") or UNSUB_WORDS.search(first):
        suppress(conn, from_addr, "replied_stop")
        conn.execute("UPDATE schools SET status='do_not_contact', updated_at=? WHERE id=? AND "
                     "NOT EXISTS (SELECT 1 FROM enrollments WHERE school_id=? AND status IN ('active','done','replied'))",
                     (db.now(), enr["school_id"], enr["school_id"]))
        conn.commit()
        return ("unsubscribed", [from_addr])
    snippet = " ".join(first.split())[:280]
    conn.execute("UPDATE enrollments SET status='replied', replied_at=?, reply_snippet=?, updated_at=? WHERE id=?",
                 (db.now(), snippet or (subject or "")[:280], db.now(), enr["id"]))
    conn.execute("UPDATE schools SET status='replied', updated_at=? WHERE id=? AND status IN ('new','queued','contacted')",
                 (db.now(), enr["school_id"]))
    db.log_activity(conn, enr["school_id"], "email",
                    f"Reply from {from_addr}: {subject[:120]}" if subject else f"Marked as replied: {from_addr}")
    conn.commit()
    return ("replied", [from_addr])


def check_replies(conn, acc, days=21):
    """Reads the inbox (without marking anything read) and stops the sequence for anyone who replied."""
    if not acc["imap_host"]:
        return {"error": "No IMAP server set for this account."}
    m = imaplib.IMAP4_SSL(acc["imap_host"], int(acc["imap_port"] or 993), ssl_context=ssl.create_default_context())
    m.login(acc["username"], account_password(acc) or "")
    try:
        m.select("INBOX", readonly=True)
        since = time.strftime("%d-%b-%Y", time.gmtime(time.time() - days * DAY))
        typ, data = m.search(None, "SINCE", since)
        ids = (data[0] or b"").split()[-500:]
        stats = {"checked": len(ids), "replied": 0, "unsubscribed": 0, "bounced": 0}
        for i in ids:
            typ, parts = m.fetch(i, "(BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.4000>)")
            raw = b"".join(p[1] for p in parts if isinstance(p, tuple))
            msg = message_from_bytes(raw)
            res = classify_inbound(conn, parseaddr(msg.get("From", ""))[1], msg.get("Subject", ""), _text_of(msg))
            if res:
                stats[res[0]] += len(res[1])
    finally:
        try:
            m.logout()
        except Exception:
            pass
    conn.execute("UPDATE accounts SET replies_checked_at=? WHERE id=?", (time.time(), acc["id"]))
    conn.commit()
    return stats


def check_next_inbox(conn, max_age=900):
    """Check the one inbox that has gone longest unchecked, if it's older than max_age seconds.
    Hosted on Vercel there is no background process, so the Email page calls this every few minutes."""
    acc = conn.execute("SELECT * FROM accounts WHERE enabled=1 AND imap_host IS NOT NULL AND imap_host!='' "
                       "AND (replies_checked_at IS NULL OR replies_checked_at<?) ORDER BY replies_checked_at "
                       "NULLS FIRST LIMIT 1", (time.time() - max_age,)).fetchone()
    if not acc:
        return {"checked": None}
    try:
        return {"account": acc["label"], **check_replies(conn, acc)}
    except Exception as e:
        conn.execute("UPDATE accounts SET replies_checked_at=?, last_error=? WHERE id=?",
                     (time.time(), f"Inbox check failed: {type(e).__name__}: {e}"[:300], acc["id"]))
        conn.commit()
        return {"account": acc["label"], "error": f"{type(e).__name__}: {e}"}


# ---------- forecast ----------

def forecast(conn, t=None):
    """How long the queue takes at the accounts' current limits (warm-up included)."""
    t = t or time.time()
    weekdays_only = settings(conn)["weekdays_only"]
    accs = [a for a in conn.execute("SELECT * FROM accounts WHERE enabled=1").fetchall() if account_password(a)]
    remaining = 0
    for r in conn.execute("SELECT country, next_step, COUNT(*) AS n FROM enrollments WHERE status='active' "
                          "GROUP BY country, next_step"):
        n_steps = len(steps(conn, r["country"]))
        remaining += max(0, n_steps - r["next_step"] + 1) * r["n"]
    first = conn.execute("SELECT COUNT(*) FROM enrollments WHERE status='active' AND next_step=1").fetchone()[0]
    per_day_now = sum(today_cap(a, t) for a in accs)
    days, left, first_left, first_days = 0, remaining, first, None
    while left > 0 and accs and days < 400:
        day_t = t + days * DAY
        days += 1
        if weekdays_only and time.gmtime(day_t).tm_wday >= 5:
            continue
        cap = sum(today_cap(a, day_t) for a in accs)
        left -= cap
        first_left -= cap
        if first_left <= 0 and first_days is None:
            first_days = days
    return {"accounts_ready": len(accs), "per_day_now": per_day_now,
            "per_day_full": sum(int(a["daily_cap"]) for a in accs), "remaining_emails": remaining,
            "first_emails": first, "days_all": days if remaining and accs else 0,
            "days_first": first_days if first else 0}
