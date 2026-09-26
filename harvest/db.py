"""SQLite storage. One file (data/harvest.db) holds the directory and the CRM."""

import json
import sqlite3
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS areas (
    code        TEXT PRIMARY KEY,          -- OCHA p-code: KE047 (county), KE047280 (sub-county)
    kind        TEXT NOT NULL,             -- county | subcounty
    name        TEXT NOT NULL,
    county_code TEXT,                      -- parent county for sub-counties
    population  INTEGER,                   -- 2019 census, total
    school_age  INTEGER,                   -- 2019 census, ages 5-19
    area_sqkm   REAL,
    lat REAL, lon REAL,
    bbox        TEXT,
    geometry    TEXT                       -- simplified GeoJSON geometry
);
CREATE INDEX IF NOT EXISTS areas_kind ON areas(kind, county_code);

CREATE TABLE IF NOT EXISTS schools (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    levels        INTEGER NOT NULL DEFAULT 0,      -- bit mask, see levels.py
    grade_min     INTEGER,                         -- -1 = PP1, 0 = PP2, 1..12 = Grade, 13 = post-secondary
    grade_max     INTEGER,
    ownership     TEXT,                            -- public | private
    sponsor       TEXT,                            -- religious | community | government | private | ngo | local_authority
    faith         TEXT,                            -- Catholic, Anglican (ACK), AIC, PCEA, SDA, Islamic, ...
    gender        TEXT,                            -- boys | girls | mixed
    boarding      TEXT,                            -- boarding | day | day_boarding
    special_needs INTEGER NOT NULL DEFAULT 0,
    -- where
    county_code TEXT, subcounty_code TEXT,
    county TEXT, subcounty TEXT,
    province TEXT, district TEXT, division TEXT, location TEXT, sublocation TEXT,
    town TEXT, postal_address TEXT,
    lat REAL, lon REAL,
    pop_density INTEGER,                           -- WorldPop 2020 people per km2 around the school
    setting TEXT,                                  -- urban | peri_urban | rural
    -- size
    classrooms INTEGER, students INTEGER, students_female INTEGER, students_male INTEGER,
    teachers INTEGER, capacity INTEGER,
    -- best-known contact points (denormalized from contacts for fast lists)
    website TEXT, phone TEXT, email TEXT,
    leader TEXT,                                   -- "Jane Wanjiru (Principal)"
    -- source identities
    moe_keys TEXT NOT NULL DEFAULT '[]',           -- json list of Ministry list rows folded in
    osm_id TEXT UNIQUE,
    wikidata TEXT,
    nemis_code TEXT,
    places_id TEXT,
    sources TEXT NOT NULL DEFAULT '[]',
    extra TEXT NOT NULL DEFAULT '{}',              -- json: fees, curriculum, other facts from the sources
    site_title TEXT, site_description TEXT,
    -- freshness
    enrich_status TEXT,         -- ok | no_site | dead | parked | blocked | error | robots
    enrich_error TEXT,
    enriched_at REAL,
    discovered_at REAL,         -- last website search
    places_at REAL,
    business_status TEXT,
    -- CRM
    status  TEXT NOT NULL DEFAULT 'new',
    starred INTEGER NOT NULL DEFAULT 0,
    tags    TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    touched_at REAL
);
CREATE INDEX IF NOT EXISTS schools_county    ON schools(county_code);
CREATE INDEX IF NOT EXISTS schools_subcounty ON schools(subcounty_code);
CREATE INDEX IF NOT EXISTS schools_levels    ON schools(levels);
CREATE INDEX IF NOT EXISTS schools_status    ON schools(status);
CREATE INDEX IF NOT EXISTS schools_name      ON schools(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS schools_enrich    ON schools(enriched_at);
CREATE INDEX IF NOT EXISTS schools_latlon    ON schools(lat, lon);
CREATE INDEX IF NOT EXISTS schools_setting   ON schools(setting);

CREATE TABLE IF NOT EXISTS contacts (
    id         INTEGER PRIMARY KEY,
    school_id  INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,    -- email phone website contact_form contact_page facebook instagram youtube x linkedin tiktok person address
    value      TEXT NOT NULL,
    label      TEXT,             -- "Principal", "admissions", ...
    source     TEXT NOT NULL,    -- moe osm wikidata web places search manual
    source_url TEXT,
    score      REAL NOT NULL DEFAULT 0,
    active     INTEGER NOT NULL DEFAULT 1,   -- 0 = no longer found at the source
    first_seen REAL NOT NULL,
    last_seen  REAL NOT NULL,
    UNIQUE(school_id, kind, value)
);
CREATE INDEX IF NOT EXISTS contacts_school ON contacts(school_id);
CREATE INDEX IF NOT EXISTS contacts_kind_value ON contacts(kind, value);

CREATE TABLE IF NOT EXISTS activities (
    id         INTEGER PRIMARY KEY,
    school_id  INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,    -- note call email meeting visit status system
    body       TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS activities_school ON activities(school_id, created_at);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    step        TEXT NOT NULL,
    args        TEXT,
    started_at  REAL NOT NULL,
    finished_at REAL,
    status      TEXT NOT NULL DEFAULT 'running',
    stats       TEXT
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE VIRTUAL TABLE IF NOT EXISTS schools_fts USING fts5(
    name, county, subcounty, place, email, website, leader, faith,
    tokenize='unicode61 remove_diacritics 2'
);
"""

STATUSES = ["new", "queued", "contacted", "replied", "interested", "visit", "partner", "not_interested",
            "do_not_contact"]
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
            _migrate(conn)
            _remote_ready = True
        return conn
    config.ensure_dirs()
    conn = sqlite3.connect(str(path or config.DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


# Columns added after the first build; added in place on older databases.
MIGRATIONS = [("schools", "email_searched_at", "REAL"), ("schools", "address", "TEXT")]


def _migrate(conn):
    for table, col, decl in MIGRATIONS:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    conn.commit()


def now():
    return time.time()


def start_run(conn, step, args=None):
    cur = conn.execute("INSERT INTO runs(step, args, started_at) VALUES (?,?,?)",
                       (step, json.dumps(args or {}), now()))
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id, stats, status="ok"):
    conn.execute("UPDATE runs SET finished_at=?, status=?, stats=? WHERE id=?",
                 (now(), status, json.dumps(stats), run_id))
    conn.commit()


def add_sources(existing_json, *new):
    cur = set(json.loads(existing_json or "[]"))
    cur.update(n for n in new if n)
    return json.dumps(sorted(cur))


SOURCE_RANK_SQL = lambda column: (f"CASE {column} WHEN 'manual' THEN 6 WHEN 'web' THEN 5 WHEN 'places' THEN 4 "  # noqa: E731
                                  "WHEN 'osm' THEN 3 WHEN 'list' THEN 3 WHEN 'wikidata' THEN 3 WHEN 'search' THEN 2 ELSE 1 END")


def upsert_contact(conn, school_id, kind, value, source, label=None, source_url=None, score=0.0, ts=None):
    ts = ts or now()
    newer_is_preferred = f"{SOURCE_RANK_SQL('excluded.source')} >= {SOURCE_RANK_SQL('contacts.source')}"
    conn.execute(
        f"""INSERT INTO contacts(school_id, kind, value, label, source, source_url, score, active, first_seen, last_seen)
           VALUES (?,?,?,?,?,?,?,1,?,?)
           ON CONFLICT(school_id, kind, value) DO UPDATE SET
             last_seen=CASE WHEN {newer_is_preferred} THEN excluded.last_seen ELSE contacts.last_seen END,
             active=CASE WHEN contacts.source='manual' AND excluded.source!='manual'
                         THEN contacts.active ELSE 1 END,
             score=MAX(contacts.score, excluded.score),
             label=CASE WHEN {newer_is_preferred} THEN COALESCE(excluded.label, contacts.label)
                        ELSE contacts.label END,
             source=CASE WHEN {newer_is_preferred} THEN excluded.source ELSE contacts.source END,
             source_url=CASE WHEN {newer_is_preferred} THEN COALESCE(excluded.source_url, contacts.source_url)
                             ELSE contacts.source_url END""",
        (school_id, kind, value, label, source, source_url, score, ts, ts),
    )


# Source trust, used when choosing which contact point to show first.
SOURCE_WEIGHT = {"manual": 100, "web": 30, "places": 25, "list": 22, "osm": 20, "wikidata": 20, "search": 15, "moe": 10}


def refresh_primary(conn, school_id):
    """Recompute the school's headline email/phone/website/leader from its contacts."""
    rows = conn.execute(
        "SELECT kind, value, label, source, score, last_seen FROM contacts WHERE school_id=? AND active=1",
        (school_id,)).fetchall()
    best = {}
    for r in rows:
        if r["label"] == "fax":
            continue
        rank = (SOURCE_WEIGHT.get(r["source"], 0) + r["score"], r["last_seen"])
        if r["kind"] not in best or rank > best[r["kind"]][0]:
            best[r["kind"]] = (rank, r)
    leader = None
    if "person" in best:
        p = best["person"][1]
        leader = p["value"] + (f" ({p['label']})" if p["label"] else "")
    fields = {
        "email": best["email"][1]["value"] if "email" in best else None,
        "phone": best["phone"][1]["value"] if "phone" in best else None,
        "website": best["website"][1]["value"] if "website" in best else None,
        "leader": leader,
    }
    if "address" in best:
        fields["postal_address"] = best["address"][1]["value"]
    conn.execute(f"UPDATE schools SET {', '.join(f'{k}=?' for k in fields)}, updated_at=? WHERE id=?",
                 (*fields.values(), now(), school_id))


FTS_COLS = "name, county, subcounty, place, email, website, leader, faith"


def fts_row(r):
    place = " ".join(x for x in (r["town"], r["location"], r["sublocation"], r["division"], r["district"]) if x)
    return (r["id"], r["name"], r["county"], r["subcounty"], place, r["email"], r["website"], r["leader"], r["faith"])


def rebuild_fts(conn):
    """The search index is rebuilt after bulk steps and
    patched per record after CRM edits (see index_one)."""
    conn.execute("DELETE FROM schools_fts")
    rows = conn.execute("SELECT * FROM schools").fetchall()
    conn.executemany(f"INSERT INTO schools_fts(rowid, {FTS_COLS}) VALUES (?,?,?,?,?,?,?,?,?)",
                     [fts_row(r) for r in rows])
    conn.commit()


def index_one(conn, school_id):
    r = conn.execute("SELECT * FROM schools WHERE id=?", (school_id,)).fetchone()
    conn.execute("DELETE FROM schools_fts WHERE rowid=?", (school_id,))
    if r:
        conn.execute(f"INSERT INTO schools_fts(rowid, {FTS_COLS}) VALUES (?,?,?,?,?,?,?,?,?)", fts_row(r))


def merge_schools(conn, keep_id, drop_id):
    """Fold drop_id into keep_id, carrying over identities, facts, contacts and CRM history."""
    keep = conn.execute("SELECT * FROM schools WHERE id=?", (keep_id,)).fetchone()
    drop = conn.execute("SELECT * FROM schools WHERE id=?", (drop_id,)).fetchone()
    if not keep or not drop:
        return
    fields = {}
    for col in ("ownership", "sponsor", "faith", "gender", "boarding", "county_code", "subcounty_code", "county",
                "subcounty", "province", "district", "division", "location", "sublocation", "town",
                "postal_address", "lat", "lon", "classrooms", "students", "students_female", "students_male",
                "teachers", "capacity", "osm_id", "wikidata", "nemis_code", "places_id", "site_title",
                "site_description", "enrich_status", "enrich_error", "enriched_at"):
        if keep[col] in (None, "") and drop[col] not in (None, ""):
            fields[col] = drop[col]
    fields["levels"] = (keep["levels"] or 0) | (drop["levels"] or 0)
    fields["special_needs"] = max(keep["special_needs"], drop["special_needs"])
    fields["sources"] = add_sources(keep["sources"], *json.loads(drop["sources"] or "[]"))
    fields["moe_keys"] = json.dumps(sorted(set(json.loads(keep["moe_keys"])) | set(json.loads(drop["moe_keys"]))))
    extra = json.loads(drop["extra"] or "{}")
    extra.update(json.loads(keep["extra"] or "{}"))
    fields["extra"] = json.dumps(extra)
    if STATUS_RANK.get(drop["status"], 0) > STATUS_RANK.get(keep["status"], 0):
        fields["status"] = drop["status"]
    fields["starred"] = max(keep["starred"], drop["starred"])
    fields["tags"] = json.dumps(sorted(set(json.loads(keep["tags"])) | set(json.loads(drop["tags"]))))
    if "osm_id" in fields:
        conn.execute("UPDATE schools SET osm_id=NULL WHERE id=?", (drop_id,))
    conn.execute(f"UPDATE schools SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                 (*fields.values(), keep_id))
    for c in conn.execute("SELECT * FROM contacts WHERE school_id=?", (drop_id,)).fetchall():
        conn.execute(
            """INSERT INTO contacts(school_id, kind, value, label, source, source_url, score, active, first_seen, last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(school_id, kind, value) DO UPDATE SET
                 last_seen=MAX(contacts.last_seen, excluded.last_seen),
                 active=MAX(contacts.active, excluded.active)""",
            (keep_id, c["kind"], c["value"], c["label"], c["source"], c["source_url"], c["score"],
             c["active"], c["first_seen"], c["last_seen"]))
    conn.execute("UPDATE activities SET school_id=? WHERE school_id=?", (keep_id, drop_id))
    conn.execute("DELETE FROM schools WHERE id=?", (drop_id,))
    from . import levels
    levels.apply_grades(conn, keep_id)
    refresh_primary(conn, keep_id)
