"""python3 -m ugschools <command>   —   see README.md"""

import argparse
import json

from . import config


def cmd_osm(args):
    from . import osm
    print(json.dumps(osm.harvest(args.file, args.raw or config.RAW_DIR), indent=2))


def cmd_merge(args):
    from . import merge
    print(json.dumps(merge.merge(args.raw or config.RAW_DIR, args.out or config.DATASET_DIR), indent=2))


def main():
    ap = argparse.ArgumentParser(prog="ugschools", description="Uganda schools directory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("osm", help="OpenStreetMap base list (HOT export) -> raw/osm.jsonl")
    p.add_argument("--file", help="an already downloaded HOT export (.zip or .geojson)")
    p.add_argument("--raw", help="raw folder (default: UG_RAW)")
    p.set_defaults(fn=cmd_osm)
    p = sub.add_parser("merge", help="raw/*.jsonl -> uganda-schools.jsonl, schools.csv, contacts.csv, summary.json")
    p.add_argument("--raw", help="raw folder (default: UG_RAW)")
    p.add_argument("--out", help="output folder (default: UG_DATASET_DIR)")
    p.set_defaults(fn=cmd_merge)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
