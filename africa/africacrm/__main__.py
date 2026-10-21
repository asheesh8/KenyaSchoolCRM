"""python3 -m africacrm <command>   —   see README.md"""

import argparse
import json
import os
import sys
import time

from . import config, db
from .countries import CODES


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def cmd_load(args):
    from . import importer
    c = db.connect()
    if args.file:
        print(json.dumps(importer.load(c, args.file, args.country), indent=2))
    elif args.country:
        p = importer.default_dataset(args.country)
        if not p:
            raise SystemExit(f"No data file found for {args.country}; pass --file.")
        print(json.dumps(importer.load(c, p, args.country), indent=2))
    else:
        print(json.dumps(importer.load_all(c), indent=2))


def cmd_import_kenya(args):
    from . import kenya
    if not (args.db or args.turso_url):
        raise SystemExit("Pass --db ../data/harvest.db (the Kenya harvester's file) or --turso-url/--turso-token.")
    out = args.out or (config.DATASET_DIR / "kenya-schools.jsonl")
    print(json.dumps(kenya.import_kenya(db.connect(), args.db, args.turso_url, args.turso_token, out), indent=2))


def cmd_stats(args):
    from .server import api_summary
    s = api_summary()
    print(f"{'Country':<16}{'on file':>10}{'email':>9}{'phone':>9}{'WhatsApp':>10}{'contacted':>11}{'replied':>9}")
    for c in s["countries"]:
        print(f"{c['flag']} {c['name']:<13}{c['total']:>10,}{c['with_email']:>9,}{c['with_phone']:>9,}"
              f"{c['with_mobile']:>10,}{c['contacted']:>11,}{c['replied']:>9,}")
    print(f"{'All':<16}{s['total']:>10,}{s['with_email']:>9,}{s['with_phone']:>9,}{s['with_mobile']:>10,}"
          f"{s['contacted']:>11,}{s['replied']:>9,}")


def cmd_send(args):
    from . import mailer
    c = db.connect()
    if args.once:
        print(json.dumps(mailer.tick(c, force=True), indent=2))
        return
    db.set_meta(c, "sending", "1")
    log("Sending is on. Each account sends inside its limits; Ctrl+C to stop (sending switches off).")
    try:
        while True:
            for a in mailer.tick(c).get("accounts", []):
                log(f"  [{a['label']}] {a['status']}  ({a.get('sent_today', 0)}/{a.get('cap_today', 0)} today)")
            r = mailer.check_next_inbox(c)
            if r.get("account"):
                log(f"  [{r['account']}] inbox: {json.dumps({k: v for k, v in r.items() if k != 'account'})}")
            time.sleep(20)
    except KeyboardInterrupt:
        db.set_meta(c, "sending", "0")
        log("\nstopped; sending switched off")


def cmd_replies(args):
    from . import mailer
    c = db.connect()
    for acc in c.execute("SELECT * FROM accounts WHERE imap_host IS NOT NULL AND imap_host!=''").fetchall():
        try:
            print(acc["label"], json.dumps(mailer.check_replies(c, acc)))
        except Exception as e:
            print(acc["label"], "failed:", e)


def cmd_publish(args):
    import sqlite3
    out = config.DATA / "publish.db"
    if out.exists():
        out.unlink()
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute(f"VACUUM INTO '{out}'")
    conn.close()
    print(f"Wrote {out}. Upload it with:\n  turso db create africa-schools --from-file {out}")


def cmd_serve(args):
    from . import server
    server.serve(args.host, args.port)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="africacrm", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("load", help="load country data files (shared format) into the CRM")
    p.add_argument("--country", choices=CODES, type=str.upper, help="only this country")
    p.add_argument("--file", help="a .jsonl file in the shared format (default: dataset/ or the project folder)")
    p.set_defaults(func=cmd_load)
    p = sub.add_parser("import-kenya", help="bring in the Kenya directory and its CRM history from the harvester")
    p.add_argument("--db", help="path to the Kenya harvester's database (usually ../data/harvest.db)")
    p.add_argument("--turso-url", help="or the live Kenya CRM's Turso database URL")
    p.add_argument("--turso-token")
    p.add_argument("--out", help="where to write kenya-schools.jsonl (default dataset/)")
    p.set_defaults(func=cmd_import_kenya)
    sub.add_parser("stats", help="print coverage by country").set_defaults(func=cmd_stats)
    p = sub.add_parser("send", help="send due emails inside each account's limits")
    p.add_argument("--once", action="store_true", help="one round only, then stop")
    p.set_defaults(func=cmd_send)
    sub.add_parser("replies", help="check every inbox for replies, stop requests and bounces") \
        .set_defaults(func=cmd_replies)
    sub.add_parser("publish", help="make a compact database copy for Turso").set_defaults(func=cmd_publish)
    p = sub.add_parser("serve", help="open the CRM")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8150)))
    p.set_defaults(func=cmd_serve)
    args = ap.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
