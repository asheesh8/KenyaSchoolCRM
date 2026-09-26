"""Check that every email's domain can receive mail (it publishes MX, or at least A, records).

An address on a domain with no mail servers can't be delivered; those contacts
are marked "no longer valid" (kept, but inactive). Uses the system `dig`.
This checks the domain, not the individual mailbox.
"""

import subprocess
from concurrent.futures import ThreadPoolExecutor

from . import db
from .net import log

KNOWN_OK = {"gmail.com", "yahoo.com", "yahoo.co.uk", "hotmail.com", "outlook.com", "live.com", "ymail.com",
            "googlemail.com", "icloud.com", "rocketmail.com", "yahoo.co.ke", "aol.com", "msn.com"}


def _dig(domain, rtype):
    try:
        out = subprocess.run(["dig", "+short", "+time=3", "+tries=2", rtype, domain], capture_output=True,
                             text=True, timeout=15).stdout.strip()
        return bool(out)
    except Exception:
        return None


def domain_ok(domain):
    if domain in KNOWN_OK:
        return True
    mx = _dig(domain, "MX")
    if mx is None:
        return None
    return mx or bool(_dig(domain, "A"))


def run(conn):
    rows = conn.execute("SELECT id, school_id, value FROM contacts WHERE kind='email' AND active=1").fetchall()
    domains = sorted({r["value"].rsplit("@", 1)[1] for r in rows})
    log(f"  checking mail servers for {len(domains):,} domains")
    with ThreadPoolExecutor(16) as pool:
        result = dict(zip(domains, pool.map(domain_ok, domains)))
    bad = [r for r in rows if result.get(r["value"].rsplit("@", 1)[1]) is False]
    touched = set()
    for r in bad:
        conn.execute("UPDATE contacts SET active=0, label='domain has no mail server' WHERE id=?", (r["id"],))
        touched.add(r["school_id"])
    for sid in touched:
        db.refresh_primary(conn, sid)
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('emails_verified_at', ?)", (str(db.now()),))
    conn.commit()
    return {"emails": len(rows), "domains": len(domains), "undeliverable": len(bad),
            "unchecked": sum(1 for v in result.values() if v is None)}
