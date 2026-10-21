"""python3 -m unittest discover tests  —  no network."""

import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ugschools import levels, merge, osm  # noqa: E402


def raw(**kw):
    rec = {"name": "Test Primary School", "kind": "school", "levels": ["primary"], "district": "Gulu",
           "emails": [], "phones": [], "officials": [], "sources": ["https://example.org/list"], "worker": "t"}
    rec.update(kw)
    return rec


def write(folder, worker, recs):
    with open(os.path.join(folder, f"{worker}.jsonl"), "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


class Rules(unittest.TestCase):
    def test_phone(self):
        self.assertEqual(levels.clean_phone("0772 123456"), "+256 772 123 456")
        self.assertEqual(levels.clean_phone("+256-414-123456"), "+256 414 123 456")
        self.assertEqual(levels.clean_phone("256 (0) 701 234 567"), "+256 701 234 567")
        self.assertEqual(levels.clean_phone("772123456"), "+256 772 123 456")
        self.assertIsNone(levels.clean_phone("12345"))
        self.assertTrue(levels.is_mobile("+256 772 123 456"))
        self.assertFalse(levels.is_mobile("+256 414 123 456"))

    def test_levels(self):
        self.assertEqual(levels.levels_from_name("Kitgum Public Primary School"), ["primary"])
        self.assertEqual(levels.levels_from_name("Gods Hope Nursery And Primary School"), ["pre_primary", "primary"])
        self.assertEqual(levels.levels_from_name("Kawempe Muslim S.S"), ["lower_secondary"])
        self.assertEqual(levels.levels_from_name("Busoga College Mwiri"), ["lower_secondary", "upper_secondary"])
        self.assertEqual(levels.levels_from_name("Kibuli Core Teacher College"), ["tertiary"])
        self.assertEqual(levels.levels_from_name("Makerere University"), ["tertiary"])
        self.assertEqual(levels.levels_from_name("Lira School of Nursing"), ["tertiary"])
        self.assertEqual(levels.levels_from_name("Elgon Technical Institute"), ["tvet"])
        self.assertEqual(levels.levels_from_name("Bweyale Seed School"), ["lower_secondary"])

    def test_district(self):
        self.assertEqual(levels.canonical_district("Luweero District"), "Luwero")
        self.assertEqual(levels.canonical_district("Gulu City"), "Gulu")
        self.assertEqual(levels.district_from_text("Plot 5, Fort Portal"), "Kabarole")
        self.assertEqual(levels.district_from_text("Ntinda, Kampala"), "Kampala")
        self.assertEqual(levels.region("Arua"), "Northern")
        self.assertEqual(len(levels.DISTRICTS), 136)

    def test_faith_and_keys(self):
        self.assertEqual(levels.faith_from_name("St. Peter's C/U Primary School"), "Anglican")
        self.assertEqual(levels.faith_from_name("St. Mary's College Kisubi"), "Catholic")
        self.assertEqual(levels.faith_from_name("Mpogo UMEA Primary School"), "Islamic")
        self.assertEqual(levels.merge_key("St. Mary's P/S"), levels.merge_key("Saint Marys Primary School"))
        self.assertNotEqual(levels.merge_key("Bweyale P/S"), levels.merge_key("Bweyale S.S"))


class OSM(unittest.TestCase):
    def test_record(self):
        feat = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [30.6, 0.6]},
                "properties": {"id": "node/1", "name": "Bright Stars Junior School", "amenity": "school",
                               "operator_type": "private", "addr_city": "Kijaguzo", "adm1_name": "Western",
                               "adm2_name": "Kyegegwa", "adm3_name": "Kyaka", "adm4_name": "Kakabara"}}
        r = osm.to_record(feat)
        self.assertEqual((r["district"], r["area"], r["ownership"], r["levels"]),
                         ("Kyegegwa", "Kakabara", "private", ["primary"]))
        self.assertEqual(r["sources"], ["https://www.openstreetmap.org/node/1"])
        self.assertIsNone(osm.to_record({"properties": {"name": "Shop", "amenity": "restaurant"}}))


class Merge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = os.path.join(self.tmp.name, "raw")
        os.makedirs(self.raw)

    def tearDown(self):
        self.tmp.cleanup()

    def run_merge(self):
        stats = merge.merge(self.raw, self.tmp.name)
        with open(os.path.join(self.tmp.name, "uganda-schools.jsonl")) as f:
            return stats, [json.loads(line) for line in f]

    def test_contacts_join_map_entry(self):
        write(self.raw, "osm", [raw(name="Layibi College", levels=["lower_secondary"], area="Laroo",
                                    osm_id="way/9", lat=2.7, lon=32.3, worker="osm",
                                    sources=["https://www.openstreetmap.org/way/9"])])
        write(self.raw, "sec", [raw(name="St. Joseph's College Layibi", levels=["lower_secondary", "upper_secondary"]),
                                raw(name="Layibi College", levels=["lower_secondary", "upper_secondary"],
                                    emails=[{"email": "Info@Layibi.ac.ug", "source_url": "https://layibi.ac.ug",
                                             "confidence": "high"}],
                                    phones=[{"phone": "0772 000111", "source_url": "https://layibi.ac.ug"}],
                                    officials=[{"name": "Jane Doe", "role": "Head Teacher",
                                                "source_url": "https://layibi.ac.ug/staff"}])])
        stats, rows = self.run_merge()
        self.assertEqual(stats["institutions"], 2)
        r = next(x for x in rows if x["name"] == "Layibi College")
        self.assertEqual(r["country"], "UG")
        self.assertEqual(r["province"], "Northern")
        self.assertEqual(r["lat"], 2.7)
        self.assertEqual(r["emails"][0]["email"], "info@layibi.ac.ug")
        self.assertEqual(r["phones"][0]["phone"], "+256 772 000 111")
        self.assertEqual(r["levels"], ["lower_secondary", "upper_secondary"])
        with open(os.path.join(self.tmp.name, "contacts.csv")) as f:
            types = [row["type"] for row in csv.DictReader(f)]
        self.assertEqual(sorted(types), ["email", "official", "whatsapp"])

    def test_unverifiable_dropped_and_same_name_kept_apart(self):
        write(self.raw, "osm", [raw(name="St. Mary's Primary School", area="A", osm_id="n/1", worker="osm"),
                                raw(name="St. Mary's Primary School", area="B", osm_id="n/2", worker="osm")])
        write(self.raw, "dir", [raw(name="St Marys P/S", sources=[],
                                    emails=[{"email": "x@y.ug"}], phones=["0772 123 456"])])
        stats, rows = self.run_merge()
        # Two same-named schools in different sub-counties stay apart; the researched record can't tell which
        # it is, so it stays separate too, and its email without a source page is dropped.
        self.assertEqual(stats["institutions"], 3)
        self.assertEqual(stats["unique_emails"], 0)
        self.assertEqual(len({r["id"] for r in rows}), 3)


if __name__ == "__main__":
    unittest.main()
