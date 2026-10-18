"""python3 -m slcrm <command>   —   see README.md"""

import argparse
import json
import os
import sys
import time

from . import config, db
from .net import log


def cmd_merge(args):
    from . import importer
    print(json.dumps(importer.merge(args.raw or config.RAW_DIR, args.out or config.DATASET_DIR), indent=2))


def cmd_load(args):
    from . import importer
    print(json.dumps(importer.load(db.connect(), args.file or config.DATASET)))


def cmd_mbsse(args):
    from . import mbsse
    print(json.dumps(mbsse.ingest(db.connect(), only=args.levels.split(",") if args.levels else None)))


def cmd_osm(args):
    from . import osm
    print(json.dumps(osm.ingest(db.connect())))


def cmd_crawl(args):
    from . import crawl
    print(json.dumps(crawl.run(db.connect(), limit=args.limit, workers=args.workers)))


def cmd_stats(args):
    from .server import api_summary, conn
    s = api_summary()
    rows = [("Institutions", s["total"]), ("  schools", s["schools"]), ("  offices / secretariats", s["offices"]),
            ("  with email", s["with_email"]), ("  unique emails", s["unique_emails"]),
            ("  with phone", s["with_phone"]), ("  with named head", s["with_leader"])]
    rows += [(f"  {lv['short']}", lv["schools"]) for lv in s["by_level"]]
    for label, n in rows:
        print(f"{label:<28}{n:>8,}")
    print("\nDistrict              in CRM  census  with email")
    for d in s["by_district"]:
        print(f"{d['district']:<20}{d['schools']:>8}{d['census']:>8}{d['with_email']:>12}")
    conn().close()


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
    print(f"Wrote {out}. Upload it with:\n  turso db create sierra-leone-schools --from-file {out}")


def cmd_serve(args):
    from . import server
    server.serve(args.host, args.port)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="slcrm", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("merge", help="fold the research files into dataset/")
    p.add_argument("--raw", help=f"folder of research .jsonl files (default {config.RAW_DIR})")
    p.add_argument("--out", help="output folder (default dataset/)")
    p.set_defaults(func=cmd_merge)
    p = sub.add_parser("load", help="load dataset/sierra-leone-schools.jsonl into the CRM")
    p.add_argument("--file")
    p.set_defaults(func=cmd_load)
    p = sub.add_parser("mbsse", help="read the Ministry's published school lists (needs internet)")
    p.add_argument("--levels", help="pre_primary,primary,junior_secondary,senior_secondary (default all)")
    p.set_defaults(func=cmd_mbsse)
    sub.add_parser("osm", help="add OpenStreetMap schools (needs internet)").set_defaults(func=cmd_osm)
    p = sub.add_parser("crawl", help="read school websites for emails, phones and heads (needs internet)")
    p.add_argument("--limit", type=int)
    p.add_argument("--workers", type=int, default=8)
    p.set_defaults(func=cmd_crawl)
    sub.add_parser("stats", help="print coverage numbers").set_defaults(func=cmd_stats)
    p = sub.add_parser("send", help="send due emails inside each account's limits")
    p.add_argument("--once", action="store_true", help="one round only, then stop")
    p.set_defaults(func=cmd_send)
    sub.add_parser("replies", help="check every inbox for replies, stop requests and bounces") \
        .set_defaults(func=cmd_replies)
    sub.add_parser("publish", help="make a compact database copy for Turso").set_defaults(func=cmd_publish)
    p = sub.add_parser("serve", help="open the CRM")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8140)))
    p.set_defaults(func=cmd_serve)
    args = ap.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
