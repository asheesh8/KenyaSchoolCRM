"""SQLite storage. One file (data/crm.db) holds the directory, the CRM and the email queue."""

import json
import sqlite3
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS schools (
    id          INTEGER PRIMARY KEY,
    ref         TEXT UNIQUE,                   -- the institution's id in dataset/sierra-leone-schools.jsonl
    name        TEXT NOT NULL,
    norm        TEXT NOT NULL,                 -- loose name key for matching map records, see levels.norm_name
    kind        TEXT NOT NULL DEFAULT 'school',-- school | office | secretariat | association | ngo
    levels      INTEGER NOT NULL DEFAULT 0,    -- bit mask, see levels.py
    ownership   TEXT,                          -- government | government_assisted | mission | private | community | ngo
    denomination TEXT,
    district    TEXT, province TEXT, chiefdom TEXT, town TEXT, address TEXT,
    lat REAL, lon REAL,
    emis_code   TEXT, osm_id TEXT,
    students    INTEGER,                       -- headcount from the Ministry's subsidy schedule
    -- best-known contact points (denormalized from contacts for fast lists)
    website TEXT, email TEXT, phone TEXT, leader TEXT,
    confidence  TEXT,                          -- best email's confidence: high | medium | low
    sources     TEXT NOT NULL DEFAULT '[]',
    notes       TEXT,
    -- CRM
    status  TEXT NOT NULL DEFAULT 'new',
    starred INTEGER NOT NULL DEFAULT 0,
    tags    TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL, updated_at REAL NOT NULL, touched_at REAL
);
CREATE INDEX IF NOT EXISTS schools_district ON schools(district);
CREATE INDEX IF NOT EXISTS schools_levels   ON schools(levels);
CREATE INDEX IF NOT EXISTS schools_status   ON schools(status);
CREATE INDEX IF NOT EXISTS schools_norm     ON schools(norm);

CREATE TABLE IF NOT EXISTS contacts (
    id         INTEGER PRIMARY KEY,
    school_id  INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,     -- email | phone | website | person
    value      TEXT NOT NULL,     -- the address / number / url, or a person's name
    person     TEXT,              -- whose email or phone it is, when known
    role       TEXT,              -- Principal, Registrar, Education Secretary, ...
    source     TEXT NOT NULL,     -- research | osm | web | manual
    source_url TEXT,
    confidence TEXT,              -- high | medium | low
    active     INTEGER NOT NULL DEFAULT 1,
    first_seen REAL NOT NULL, last_seen REAL NOT NULL,
    UNIQUE(school_id, kind, value)
);
CREATE INDEX IF NOT EXISTS contacts_school ON contacts(school_id);
CREATE INDEX IF NOT EXISTS contacts_value  ON contacts(kind, value);

CREATE TABLE IF NOT EXISTS activities (
    id         INTEGER PRIMARY KEY,
    school_id  INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,     -- note call email meeting visit status system
    body       TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS activities_school ON activities(school_id, created_at);

-- Up to seven sending mailboxes.
CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY,
    label         TEXT NOT NULL,
    from_name     TEXT,
    from_email    TEXT NOT NULL,
    reply_to      TEXT,
    provider      TEXT,               -- gmail | outlook | zoho | yahoo | custom
    smtp_host     TEXT NOT NULL, smtp_port INTEGER NOT NULL, smtp_security TEXT NOT NULL DEFAULT 'starttls',
    imap_host     TEXT, imap_port INTEGER DEFAULT 993,
    username      TEXT NOT NULL,
    password_enc  TEXT,               -- encrypted with SECRET_KEY; SENDER_<id>_PASSWORD overrides
    daily_cap     INTEGER NOT NULL DEFAULT 40,
    hourly_cap    INTEGER NOT NULL DEFAULT 10,
    min_gap_s     INTEGER NOT NULL DEFAULT 120,
    warmup        INTEGER NOT NULL DEFAULT 1,
    warmup_start  INTEGER NOT NULL DEFAULT 10,
    warmup_step   INTEGER NOT NULL DEFAULT 5,
    window_start  INTEGER NOT NULL DEFAULT 8,   -- send only between these hours, Freetown time (GMT)
    window_end    INTEGER NOT NULL DEFAULT 18,
    signature     TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    first_send_at REAL, last_sent_at REAL, next_allowed_at REAL,
    fail_streak   INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    lock_until    REAL,
    replies_checked_at REAL,
    created_at    REAL NOT NULL
);

-- The three-step sequence. Step 1 goes out when a contact is enrolled; later steps wait delay_days.
CREATE TABLE IF NOT EXISTS templates (
    step       INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    subject    TEXT NOT NULL,      -- empty for steps 2-3 = reply in the same thread ("Re: ...")
    body       TEXT NOT NULL,
    delay_days REAL NOT NULL DEFAULT 0
);

-- One row per recipient email moving through the sequence.
CREATE TABLE IF NOT EXISTS enrollments (
    id          INTEGER PRIMARY KEY,
    school_id   INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    email       TEXT NOT NULL UNIQUE,
    person      TEXT, role TEXT,
    account_id  INTEGER NOT NULL REFERENCES accounts(id),
    next_step   INTEGER NOT NULL DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'active',  -- active | paused | done | replied | unsubscribed | bounced | failed
    next_due_at REAL NOT NULL,
    thread_id   TEXT, thread_subject TEXT,       -- Message-ID and subject of step 1, for follow-ups
    created_at  REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS enrollments_due ON enrollments(account_id, status, next_due_at);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    enrollment_id INTEGER, school_id INTEGER, account_id INTEGER,
    to_email    TEXT NOT NULL, step INTEGER, subject TEXT,
    status      TEXT NOT NULL,       -- sent | failed
    error       TEXT, message_id TEXT,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_account ON messages(account_id, created_at);

CREATE TABLE IF NOT EXISTS suppressions (
    email      TEXT PRIMARY KEY,
    reason     TEXT NOT NULL,        -- unsubscribed | bounced | replied_stop | manual
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

STATUSES = ["new", "queued", "contacted", "replied", "interested", "partner", "not_interested", "do_not_contact"]
STATUS_RANK = {s: i for i, s in enumerate(STATUSES)}
STATUS_RANK["do_not_contact"] = 99

_remote_ready = False


def connect(path=None):
    """The local SQLite file, or the hosted Turso database when it's configured."""
    global _remote_ready
    if config.TURSO_URL and path is None:
        from . import remote
        conn = remote.connect(config.TURSO_URL, config.TURSO_TOKEN)
        if not _remote_ready:
            conn.executescript(SCHEMA)
            _seed(conn)
            _remote_ready = True
        return conn
    config.ensure_dirs()
    conn = sqlite3.connect(str(path or config.DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    _seed(conn)
    return conn


def _seed(conn):
    if not conn.execute("SELECT COUNT(*) FROM templates").fetchone()[0]:
        from .mailer import DEFAULT_TEMPLATES
        for t in DEFAULT_TEMPLATES:
            conn.execute("INSERT INTO templates(step, name, subject, body, delay_days) VALUES (?,?,?,?,?)",
                         (t["step"], t["name"], t["subject"], t["body"], t["delay_days"]))
        conn.commit()


def now():
    return time.time()


def get_meta(conn, key, default=None):
    r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def set_meta(conn, key, value):
    conn.execute("INSERT INTO meta(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, None if value is None else str(value)))
    conn.commit()


def add_sources(existing_json, *new):
    cur = set(json.loads(existing_json or "[]"))
    cur.update(n for n in new if n)
    return json.dumps(sorted(cur))


CONF_RANK = {"high": 3, "medium": 2, "low": 1, None: 0}
SOURCE_RANK = {"manual": 4, "web": 3, "research": 3, "osm": 2}


def upsert_contact(conn, school_id, kind, value, source, person=None, role=None, source_url=None,
                   confidence=None, ts=None):
    ts = ts or now()
    conn.execute(
        """INSERT INTO contacts(school_id, kind, value, person, role, source, source_url, confidence, active,
                                first_seen, last_seen)
           VALUES (?,?,?,?,?,?,?,?,1,?,?)
           ON CONFLICT(school_id, kind, value) DO UPDATE SET
             last_seen=excluded.last_seen,
             person=COALESCE(contacts.person, excluded.person),
             role=COALESCE(contacts.role, excluded.role),
             source_url=COALESCE(contacts.source_url, excluded.source_url),
             confidence=CASE WHEN COALESCE(excluded.confidence,'') IN ('high')
                               OR contacts.confidence IS NULL THEN excluded.confidence
                             ELSE contacts.confidence END""",
        (school_id, kind, value, person, role, source, source_url, confidence, ts, ts))


def refresh_primary(conn, school_id):
    """Recompute the school's headline email / phone / website / leader from its contacts."""
    rows = conn.execute("SELECT * FROM contacts WHERE school_id=? AND active=1", (school_id,)).fetchall()
    best = {}
    for r in rows:
        # Role addresses of the school itself beat a named person's address for the headline.
        rank = (CONF_RANK.get(r["confidence"], 0), SOURCE_RANK.get(r["source"], 0), r["person"] is None,
                r["last_seen"])
        if r["kind"] not in best or rank > best[r["kind"]][0]:
            best[r["kind"]] = (rank, r)
    leader = None
    if "person" in best:
        p = best["person"][1]
        leader = p["value"] + (f" ({p['role']})" if p["role"] else "")
    email = best.get("email", (None, None))[1]
    conn.execute(
        "UPDATE schools SET email=?, phone=?, website=?, leader=?, confidence=?, updated_at=? WHERE id=?",
        (email["value"] if email else None,
         best["phone"][1]["value"] if "phone" in best else None,
         best["website"][1]["value"] if "website" in best else None,
         leader, email["confidence"] if email else None, now(), school_id))


def log_activity(conn, school_id, kind, body):
    t = now()
    conn.execute("INSERT INTO activities(school_id, kind, body, created_at) VALUES (?,?,?,?)",
                 (school_id, kind, body, t))
    conn.execute("UPDATE schools SET touched_at=? WHERE id=?", (t, school_id))
