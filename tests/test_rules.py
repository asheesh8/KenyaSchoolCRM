"""Rule tests: python3 -m unittest discover tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harvest import extract, levels, moe, osm  # noqa: E402


class Levels(unittest.TestCase):
    def test_moe_levels(self):
        self.assertEqual(levels.moe_level("ECD/PRE-PRIMARY SCHOOL", "X ECD"), levels.ECDE)
        self.assertEqual(levels.moe_level("SECONDARY SCH", "X SEC"), levels.SENIOR)
        self.assertEqual(levels.moe_level("YOUTH POLYTECHNIC", "X"), levels.TVET)
        self.assertEqual(levels.moe_level("", "KIRU PRI SCH"), levels.PRIMARY)

    def test_levels_from_name(self):
        self.assertEqual(levels.levels_from_name("Alliance Girls High School"), levels.SENIOR)
        self.assertEqual(levels.levels_from_name("Kenyatta University"), levels.UNIVERSITY)
        self.assertEqual(levels.levels_from_name("Kagumo Teachers Training College"), levels.TTC)
        self.assertEqual(levels.levels_from_name("Sunrise Academy"), levels.PRIMARY)
        self.assertTrue(levels.levels_from_name("Mugoiri Comprehensive School") & levels.JUNIOR)

    def test_grades(self):
        self.assertEqual(levels.grades_for(levels.ECDE | levels.PRIMARY), (-1, 6))
        self.assertEqual(levels.grades_for(levels.SENIOR), (10, 12))
        mask = levels.mask_for_grades([8])
        self.assertTrue(mask & levels.JUNIOR and mask & levels.PRIMARY)
        self.assertFalse(levels.mask_for_grades([8], primary_hosts_junior=False) & levels.PRIMARY)
        self.assertTrue(levels.mask_for_grades([13]) & levels.UNIVERSITY)

    def test_osm_isced(self):
        self.assertEqual(levels.osm_levels({"amenity": "school", "isced:level": "0;1", "name": "X"}),
                         levels.ECDE | levels.PRIMARY)
        self.assertEqual(levels.osm_levels({"amenity": "kindergarten", "name": "Little Stars"}), levels.ECDE)

    def test_map_cannot_make_a_primary_secondary(self):
        mapped = levels.PRIMARY | levels.JUNIOR | levels.SENIOR | levels.TVET  # isced:level=2;3;4
        self.assertEqual(osm.combine_levels(levels.PRIMARY, mapped, "Githinji Primary"), levels.PRIMARY | levels.JUNIOR)
        self.assertTrue(osm.combine_levels(levels.PRIMARY, mapped, "Githinji Primary and Secondary") & levels.SENIOR)

    def test_names(self):
        self.assertEqual(levels.display_name("ST. PATRICK KIMALA PRI SCH"), "St. Patrick Kimala Primary School")
        self.assertEqual(levels.display_name("ACK ST MARY'S GIRLS SEC SCH"), "ACK St. Mary's Girls Secondary School")
        self.assertEqual(levels.display_name("Brookhouse School"), "Brookhouse School")
        self.assertEqual(levels.base_name("GUBIS PRE-SCHOOL"), levels.base_name("GUBIS PRIMARY SCHOOL"))

    def test_facts_from_name(self):
        self.assertEqual(levels.gender_from_name("Moi Girls High School"), "girls")
        self.assertEqual(levels.faith_from_name("AIC Kijabe Primary"), "Africa Inland Church")
        self.assertEqual(levels.faith_from_name("PCEA Tumutumu Girls"), "Presbyterian (PCEA)")
        self.assertEqual(levels.faith_from_name("Nairobi Muslim Academy"), "Islamic")
        self.assertIsNone(levels.faith_from_name("Kibera Primary School"))
        self.assertEqual(levels.special_from_name("Kiru Special Unit"), 1)


class Folding(unittest.TestCase):
    def row(self, name, level, lat=-1.0, lon=37.0, source="moe2010"):
        return {"key": name + level, "source": source, "name": name, "level_text": level, "lat": lat, "lon": lon}

    def test_ecd_joins_its_primary(self):
        g = moe.group_rows([self.row("GUBIS PRE-SCHOOL", "ECD/PRE-PRIMARY SCHOOL"),
                            self.row("GUBIS PRIMARY SCHOOL", "PRIMARY SCHOOL")])
        self.assertEqual(len(g), 1)

    def test_typo_at_same_spot_still_folds(self):
        g = moe.group_rows([self.row("ABERDARE ECD", "ECD/PRE-PRIMARY SCHOOL"),
                            self.row("ARBERDARE PRIMARY", "PRIMARY SCHOOL")])
        self.assertEqual(len(g), 1)

    def test_secondary_stays_separate(self):
        g = moe.group_rows([self.row("BAVUNI PRIMARY", "PRIMARY SCHOOL"),
                            self.row("BAVUNI SECONDARY", "SECONDARY SCHOOL")])
        self.assertEqual(len(g), 2)

    def test_two_primaries_stay_separate(self):
        g = moe.group_rows([self.row("KIAMBU PRIMARY", "PRIMARY SCHOOL"),
                            self.row("KIAMBU PRIMARY", "PRIMARY SCHOOL", lat=-1.001)])
        self.assertEqual(len(g), 2)

    def test_matching_scores(self):
        t = levels.tokens
        self.assertGreaterEqual(osm.name_score(t("Kibera Primary School"), t("KIBERA PRI SCH")), 1.0)
        self.assertLess(osm.name_score(t("Moi Girls"), t("Moi Forces Academy")), 0.6)


class Extraction(unittest.TestCase):
    def test_phones(self):
        self.assertEqual(extract.normalize_phone("0722 699 646"), "+254 722 699 646")
        self.assertEqual(extract.normalize_phone("+254 (0) 722-699646"), "+254 722 699 646")
        self.assertEqual(extract.normalize_phone("020 2345678"), "+254 20 234 5678")
        self.assertEqual(extract.normalize_phone("0110 123 456"), "+254 110 123 456")
        self.assertIsNone(extract.normalize_phone("+256782059913"))  # Uganda
        self.assertIsNone(extract.normalize_phone("0700 000 000"))

    def test_page(self):
        html = """<title>Alliance Girls High School</title>
          <p>P.O. Box 123-00902, Kikuyu, Kenya. Tel: 0722 699 646 / 020-2345678.</p>
          <a href="mailto:info@alliancegirls.sc.ke">Email us</a>
          <h3>Principal: Mrs. Virginia Wahome</h3><p>Deputy Principal - Mr. John Kamau Mwangi</p>
          <p>We have over 1,200 students</p><a href="https://wa.me/254722000111">WhatsApp</a>"""
        r = extract.extract(html, "https://alliancegirls.sc.ke/")
        self.assertIn("info@alliancegirls.sc.ke", r["emails"])
        self.assertIn("+254 722 699 646", r["phones"])
        self.assertEqual(r["phones"]["+254 722 000 111"]["label"], "WhatsApp")
        self.assertIn("P.O. Box 123-00902, Kikuyu", r["addresses"])
        self.assertEqual(r["people"]["Virginia Wahome"]["title"], "Principal")
        self.assertEqual(r["people"]["John Kamau Mwangi"]["title"], "Deputy principal")
        self.assertEqual(r["students"], 1200)

    def test_registrable(self):
        self.assertEqual(extract.registrable("www.alliancegirls.sc.ke"), "alliancegirls.sc.ke")
        self.assertEqual(extract.registrable("portal.riaraschools.ac.ke"), "riaraschools.ac.ke")

    def test_public_urls_only(self):
        from harvest import net
        self.assertFalse(net.is_public_url("http://127.0.0.1/"))
        self.assertFalse(net.is_public_url("file:///etc/passwd"))


if __name__ == "__main__":
    unittest.main()
