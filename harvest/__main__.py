"""python3 -m harvest <command> [options]   —   see README.md"""

import argparse
import json
import os
import sys
import time

from . import config, db
from .net import log

STEPS = ("areas", "moe", "osm", "wikidata", "teacher", "eeg", "enh", "tveta", "dedupe", "discover", "ccsites", "crawl", "emails", "verify", "address", "places")


def _counties(conn, arg):
    """'Nairobi,kisumu' or 'KE047' -> county p-codes; empty -> every county."""
    if not arg:
        return None
    rows = conn.execute("SELECT code, name FROM areas WHERE kind='county'").fetchall()
    by = {r["name"].lower(): r["code"] for r in rows}
    by.update({r["code"].lower(): r["code"] for r in rows})
    out = []
    for part in arg.split(","):
        key = part.strip().lower().replace("-", " ")
        if key not in by:
            raise SystemExit(f"Unknown county: {part}. Run `python3 -m harvest areas` first, or check the spelling.")
        out.append(by[key])
    return out


def _run_step(conn, step, args):
    from . import address, areas, ccsites, crawl, dedupe, discover, eeg, emails, enh, tveta, verify, moe, osm, places, teacher, wikidata
    t0 = time.time()
    log(f"\n== {step}")
    run_id = db.start_run(conn, step, {k: v for k, v in vars(args).items() if k != "func"})
    counties = _counties(conn, getattr(args, "counties", None)) if step not in ("areas",) else None
    try:
        if step == "areas":
            stats = areas.build(conn)
        elif step == "moe":
            stats = moe.ingest(conn)
        elif step == "osm":
            stats = osm.ingest(conn)
        elif step == "wikidata":
            stats = wikidata.ingest(conn)
        elif step == "teacher":
            stats = teacher.ingest(conn)
        elif step == "eeg":
            stats = eeg.ingest(conn)
        elif step == "enh":
            stats = enh.ingest(conn, limit=args.limit)
        elif step == "tveta":
            stats = tveta.ingest(conn)
        elif step == "dedupe":
            stats = dedupe.run(conn)
        elif step == "discover":
            stats = discover.run(conn, counties=counties, limit=args.limit, levels=args.levels,
                                 stale_days=args.stale_days, workers=args.workers)
        elif step == "ccsites":
            stats = ccsites.run(conn, workers=args.workers)
        elif step == "crawl":
            stats = crawl.run(conn, counties, stale_days=args.stale_days, limit=args.limit, workers=args.workers,
                              missing_email=args.missing_email)
        elif step == "emails":
            stats = emails.run(conn, counties, limit=args.limit, levels_arg=args.levels)
        elif step == "verify":
            stats = verify.run(conn)
        elif step == "address":
            stats = address.run(conn)
        elif step == "places":
            stats = places.run(conn, counties, limit=args.limit, stale_days=args.stale_days or 180,
                               levels=args.levels)
        else:
            raise SystemExit(f"unknown step {step}")
        if step in ("moe", "osm", "wikidata", "teacher", "eeg", "enh", "tveta", "dedupe", "discover", "emails", "places"):
            db.rebuild_fts(conn)
    except KeyboardInterrupt:
        conn.commit()
        db.finish_run(conn, run_id, {"interrupted": True}, status="interrupted")
        raise
    except Exception as e:
        conn.commit()
        db.finish_run(conn, run_id, {"error": str(e)}, status="error")
        raise
    stats["seconds"] = round(time.time() - t0)
    db.finish_run(conn, run_id, stats)
    log(f"   {json.dumps(stats)}")
    return stats


def cmd_step(args):
    conn = db.connect()
    _run_step(conn, args.step, args)


def cmd_all(args):
    conn = db.connect()
    have_areas = conn.execute("SELECT COUNT(*) FROM areas").fetchone()[0]
    for step in (("areas",) if not have_areas else ()) + ("moe", "osm", "wikidata", "teacher", "eeg", "enh", "dedupe"):
        _run_step(conn, step, args)
    if not args.skip_crawl:
        _run_step(conn, "discover", args)
        _run_step(conn, "crawl", args)
    cmd_stats(args, conn)


def cmd_stats(args, conn=None):
    conn = conn or db.connect()
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    total = q("SELECT COUNT(*) FROM schools")
    counties = q("SELECT COUNT(*) FROM areas WHERE kind='county'")
    constituencies = q("SELECT COUNT(*) FROM areas WHERE kind='subcounty'")
    rows = [
        ("Counties / constituencies", f"{counties} / {constituencies}"),
        ("Schools", total),
        ("  pre-primary", q("SELECT COUNT(*) FROM schools WHERE levels & 1")),
        ("  primary", q("SELECT COUNT(*) FROM schools WHERE levels & 2")),
        ("  junior school", q("SELECT COUNT(*) FROM schools WHERE levels & 4")),
        ("  senior / secondary", q("SELECT COUNT(*) FROM schools WHERE levels & 8")),
        ("  post-secondary", q("SELECT COUNT(*) FROM schools WHERE levels & (16|32|64)")),
        ("  public", q("SELECT COUNT(*) FROM schools WHERE ownership='public'")),
        ("  private", q("SELECT COUNT(*) FROM schools WHERE ownership='private'")),
        ("  with phone", q("SELECT COUNT(*) FROM schools WHERE phone IS NOT NULL")),
        ("  with email", q("SELECT COUNT(*) FROM schools WHERE email IS NOT NULL")),
        ("  with website", q("SELECT COUNT(*) FROM schools WHERE website IS NOT NULL")),
        ("  with named head", q("SELECT COUNT(*) FROM schools WHERE leader IS NOT NULL")),
        ("  with postal address", q("SELECT COUNT(*) FROM schools WHERE postal_address IS NOT NULL")),
        ("  website checked", q("SELECT COUNT(*) FROM schools WHERE enriched_at IS NOT NULL")),
    ]
    for label, n in rows:
        pct = f"  ({n / total:.1%})" if total and isinstance(n, int) and label.startswith("  ") else ""
        print(f"{label:<28}{n:>10,}{pct}" if isinstance(n, int) else f"{label:<28}{n:>10}")


def cmd_publish(args):
    """Write a compact copy of the database for uploading to Turso."""
    import sqlite3
    out = config.DATA / "publish.db"
    if out.exists():
        out.unlink()
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute(f"VACUUM INTO '{out}'")
    conn.close()
    size = out.stat().st_size / 1e6
    print(f"Wrote {out} ({size:.0f} MB). Upload it with:\n"
          f"  turso db create kenya-schools --from-file {out}\n"
          f"  turso db show kenya-schools --url\n"
          f"  turso db tokens create kenya-schools")


def cmd_serve(args):
    from . import server
    server.serve(args.host, args.port)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="harvest", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--counties", help="comma-separated county names, e.g. Nairobi,Kisumu (default: all 47)")
        p.add_argument("--limit", type=int, help="at most this many schools (discover/crawl/places)")
        p.add_argument("--stale-days", type=float, help="re-check anything last checked more than N days ago")
        p.add_argument("--workers", type=int, default=16, help="parallel lookups (discover/crawl)")
        p.add_argument("--levels", help="discover/places: level keys, e.g. senior,tvet,university "
                                        "(default: senior, post-secondary and private schools)")
        p.add_argument("--missing-email", action="store_true", help="crawl: focus on sites without an email")

    for step in STEPS:
        p = sub.add_parser(step, help=f"run the {step} step")
        common(p)
        p.set_defaults(func=cmd_step, step=step)

    p = sub.add_parser("all", help="run every free step in order")
    common(p)
    p.add_argument("--skip-crawl", action="store_true", help="stop before looking for and reading websites")
    p.set_defaults(func=cmd_all)

    p = sub.add_parser("stats", help="print coverage numbers")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("publish", help="make a compact database copy for Turso (hosted deployments)")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("serve", help="open the CRM")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8130)))
    p.set_defaults(func=cmd_serve)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        log("\ninterrupted — progress so far is saved; re-run to continue")
        sys.exit(130)


if __name__ == "__main__":
    main()
