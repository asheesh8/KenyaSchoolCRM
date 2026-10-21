"""python3 -m unittest discover tests  —  no network, no real email."""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ["AFRICACRM_DATA"] = tempfile.mkdtemp()
os.environ["AFRICACRM_PROJECT_FILES"] = tempfile.mkdtemp()

from africacrm import config, db, importer, kenya, levels, mailer, phone, server  # noqa: E402
from africacrm.countries import get  # noqa: E402

MONDAY_06_GMT = 1760940000.0   # Mon 2025-10-20 06:00 GMT = 09:00 in Nairobi and Kampala
MONDAY_10_GMT = 1760954400.0   # Mon 2025-10-20 10:00 GMT
SATURDAY_10_GMT = MONDAY_10_GMT + 5 * 86400


def rec(**kw):
    r = {"name": "Test School", "kind": "school", "levels": ["primary"], "district": "Bo", "town": "Bo",
         "emails": [], "phones": [], "officials": [], "sources": ["https://example.org/list"]}
    r.update(kw)
    return r


def fresh():
    c = db.connect(Path(tempfile.mkdtemp()) / "t.db")
    server._local.conn = c
    return c


def add_account(c, aid=1, countries="", **kw):
    vals = dict(id=aid, label=f"acct{aid}", from_name="Ash", from_email=f"a{aid}@example.org", smtp_host="smtp.x",
                smtp_port=587, username=f"a{aid}@example.org", password_enc=mailer.encrypt("pw"), daily_cap=40,
                hourly_cap=10, min_gap_s=30, warmup=0, countries=countries, created_at=1.0)
    vals.update(kw)
    c.execute(f"INSERT INTO accounts({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", list(vals.values()))
    c.commit()


def load(c, country, *records):
    return importer.load_records(c, [importer.normalize(r, country) for r in records], country)


class Countries(unittest.TestCase):
    def test_phones(self):
        ke, sl, ug = get("KE"), get("SL"), get("UG")
        self.assertEqual(ke.clean_phone("0722 123456"), "+254 722 123 456")
        self.assertEqual(sl.clean_phone("076 123 456"), "+232 76 123 456")
        self.assertEqual(ug.clean_phone("+256-414-123456"), "+256 414 123 456")
        self.assertTrue(ug.is_mobile("+256 772 123 456"))
        self.assertFalse(ug.is_mobile("+256 414 123 456"))
        self.assertFalse(sl.is_mobile("+232 22 223 444"))
        self.assertTrue(ke.is_mobile("+254 110 123 456"))

    def test_districts(self):
        self.assertEqual(get("KE").canonical_district("ELGEYO-MARAKWET"), "Elgeyo Marakwet")
        self.assertEqual(get("SL").canonical_district("Freetown"), "Western Area Urban")
        self.assertEqual(get("UG").canonical_district("WAKISO"), "Wakiso")  # no fixed list: tidied, kept

    def test_shared_levels(self):
        self.assertEqual(levels.clean_keys(["junior_secondary", "senior_secondary"]), ["lower_secondary", "upper_secondary"])
        self.assertEqual(levels.levels_from_name("St Mary's College Kisubi", get("UG").name_rules),
                         ["lower_secondary", "upper_secondary"])
        self.assertEqual(levels.levels_from_name("Kyambogo University", get("UG").name_rules), ["tertiary"])


class Import(unittest.TestCase):
    def test_normalize_drops_unsourced_email_and_maps_area(self):
        r = importer.normalize(rec(sources=["https://a.org", "https://b.org"], emails=[{"email": "x@y.org"}],
                                   chiefdom="Kakua"), "SL")
        self.assertEqual(r["emails"], [])
        self.assertEqual(r["area"], "Kakua")
        self.assertEqual(r["province"], "South")
        u = importer.normalize(rec(district="Wakiso", province="Central", subcounty="Gayaza",
                                   phones=["0772 766364"]), "UG")
        self.assertEqual((u["district"], u["province"], u["area"]), ("Wakiso", "Central", "Gayaza"))
        self.assertEqual(u["phones"][0]["phone"], "+256 772 766 364")

    def test_reload_keeps_crm_state(self):
        c = fresh()
        _, ids = load(c, "SL", rec(id="a1", emails=[{"email": "head@bo.sl", "source_url": "https://bo.sl"}]))
        sid = ids["a1"]
        server.api_patch_school(sid, {"status": "interested"})
        load(c, "SL", rec(id="a1", name="Test School (renamed)"))
        row = c.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
        self.assertEqual((row["status"], row["name"], row["email"]), ("interested", "Test School (renamed)", "head@bo.sl"))

    def test_same_ref_in_two_countries_is_two_schools(self):
        c = fresh()
        load(c, "SL", rec(id="x"))
        load(c, "UG", rec(id="x", district="Kampala"))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM schools").fetchone()[0], 2)

    def test_load_file(self):
        c = fresh()
        p = Path(tempfile.mkdtemp()) / "ug.jsonl"
        p.write_text(json.dumps(rec(id="u1", country="UG", district="Gulu", province="Northern")) + "\n")
        self.assertEqual(importer.load(c, p)["UG"]["added"], 1)
        with self.assertRaises(ValueError):
            p.write_text(json.dumps(rec(id="u2")) + "\n")
            importer.load(c, p)

    def test_legacy_database_is_refused(self):
        path = Path(tempfile.mkdtemp()) / "old.db"
        old = sqlite3.connect(path)
        old.execute("CREATE TABLE schools (id INTEGER PRIMARY KEY, name TEXT)")
        old.commit()
        old.close()
        with self.assertRaises(db.WrongDatabase):
            db.connect(path)


class KenyaImport(unittest.TestCase):
    def harvest_db(self):
        sys.path.insert(0, str(ROOT.parent))
        try:
            from harvest import db as hdb
        except ImportError:
            self.skipTest("the Kenya harvester isn't next to this folder")
        path = Path(tempfile.mkdtemp()) / "harvest.db"
        h = sqlite3.connect(path)
        h.row_factory = sqlite3.Row
        h.executescript(hdb.SCHEMA)
        for table, col, decl in hdb.MIGRATIONS:
            h.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        h.execute("INSERT INTO schools(id, name, levels, ownership, sponsor, faith, county, subcounty, province, town, "
                  "status, starred, tags, created_at, updated_at, touched_at, sources) VALUES "
                  "(7, 'Alliance High School', 8, 'public', 'religious', 'PCEA', 'Kiambu', 'Kikuyu', 'Central', "
                  "'Kikuyu', 'visit', 1, '[\"top\"]', 1, 1, 5, '[\"https://alliancehigh.ac.ke\"]')")
        h.execute("INSERT INTO schools(id, name, levels, ownership, county, created_at, updated_at, sources) VALUES "
                  "(8, 'Kibera Primary', 3, 'public', 'Nairobi City', 1, 1, '[]')")
        for kind, value, label, source in (("email", "info@alliancehigh.ac.ke", None, "web"),
                                           ("phone", "+254 722 000 111", None, "web"),
                                           ("phone", "+254 20 2012345", "fax", "web"),
                                           ("person", "Jane Doe", "Principal", "web")):
            h.execute("INSERT INTO contacts(school_id, kind, value, label, source, source_url, first_seen, last_seen) "
                      "VALUES (7,?,?,?,?, 'https://alliancehigh.ac.ke/contact', 1, 1)", (kind, value, label, source))
        h.execute("INSERT INTO activities(school_id, kind, body, created_at) VALUES (7, 'call', 'Spoke to the deputy', 3)")
        h.execute("INSERT INTO areas(code, kind, name, population, school_age) VALUES ('KE022', 'county', 'Kiambu', "
                  "2417735, 700000)")
        h.commit()
        h.close()
        return path

    def test_import_carries_over_directory_and_crm(self):
        path = self.harvest_db()
        c = fresh()
        out = Path(tempfile.mkdtemp()) / "kenya-schools.jsonl"
        stats = kenya.import_kenya(c, path, out=out)
        self.assertEqual((stats["added"], stats["crm_state_carried_over"], stats["activities_copied"]), (2, 1, 1))
        s = c.execute("SELECT * FROM schools WHERE ref='ke-7'").fetchone()
        self.assertEqual((s["country"], s["district"], s["status"], s["starred"]), ("KE", "Kiambu", "interested", 1))
        self.assertEqual(levels.keys(s["levels"]), ["upper_secondary"])
        self.assertEqual((s["email"], s["mobile"], s["leader"]), ("info@alliancehigh.ac.ke", "+254 722 000 111",
                                                                  "Jane Doe (Principal)"))
        self.assertEqual(c.execute("SELECT district FROM schools WHERE ref='ke-8'").fetchone()[0], "Nairobi")
        self.assertEqual(c.execute("SELECT population FROM regions WHERE country='KE' AND district='Kiambu'")
                         .fetchone()[0], 2417735)
        self.assertEqual(len(out.read_text().splitlines()), 2)
        kenya.import_kenya(c, path)  # running it again adds nothing twice
        self.assertEqual(c.execute("SELECT COUNT(*) FROM activities WHERE body='Spoke to the deputy'").fetchone()[0], 1)


class Email(unittest.TestCase):
    def setUp(self):
        self.c = fresh()
        _, self.sl = load(self.c, "SL", *[rec(id=f"s{i}", name=f"Bo School {i}", emails=[
            {"email": f"head{i}@bo.sl", "source_url": "https://bo.sl"}]) for i in range(4)])
        _, self.ug = load(self.c, "UG", rec(id="u1", name="Gulu High", district="Gulu", province="Northern",
                                            emails=[{"email": "gulu@high.ug", "source_url": "https://gulu.ug"}]))

    def test_enroll_spreads_and_respects_account_countries(self):
        add_account(self.c, 1)
        add_account(self.c, 2, countries="UG")
        st = mailer.enroll(self.c, list(self.sl.values()) + list(self.ug.values()), campaign="Oct")
        self.assertEqual(st["enrolled"], 5)
        rows = {r["email"]: r["account_id"] for r in self.c.execute("SELECT * FROM enrollments")}
        self.assertTrue(all(rows[f"head{i}@bo.sl"] == 1 for i in range(4)))  # account 2 only emails Uganda
        self.assertEqual(rows["gulu@high.ug"], 2)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM enrollments WHERE campaign='Oct'").fetchone()[0], 5)

    def test_sends_in_each_schools_local_hours(self):
        add_account(self.c, 1)
        mailer.enroll(self.c, list(self.sl.values())[:1] + list(self.ug.values()), t=MONDAY_06_GMT - 60)
        sent = []
        res = mailer.tick(self.c, send_fn=lambda a, m: sent.append(m["To"]), t=MONDAY_06_GMT, force=True)
        self.assertEqual(sent, ["gulu@high.ug"])  # 09:00 in Kampala, 06:00 in Freetown
        self.assertIn("sent email 1", res["accounts"][0]["status"])
        ok, reason, _ = mailer.allowance(self.c, self.c.execute("SELECT * FROM accounts").fetchone(), SATURDAY_10_GMT)
        self.assertFalse(ok)
        self.assertIn("outside sending hours", reason)

    def test_followup_threads_and_reply_stops(self):
        add_account(self.c, 1)
        sid = self.ug["u1"]
        mailer.enroll(self.c, [sid], t=MONDAY_10_GMT - 60)
        msgs = []
        mailer.tick(self.c, send_fn=lambda a, m: msgs.append(m), t=MONDAY_10_GMT, force=True)
        self.assertIn("Uganda", msgs[0].get_content())
        e = self.c.execute("SELECT * FROM enrollments").fetchone()
        self.assertEqual(e["next_step"], 2)
        mailer.classify_inbound(self.c, "gulu@high.ug", "Re: A free Bible library", "Yes please, we have 600 pupils.")
        e = self.c.execute("SELECT * FROM enrollments").fetchone()
        self.assertEqual((e["status"], e["reply_snippet"]), ("replied", "Yes please, we have 600 pupils."))
        self.assertEqual(server.api_replies({})["email"][0]["school"], "Gulu High")

    def test_stop_reply_suppresses_everywhere(self):
        add_account(self.c, 1)
        mailer.enroll(self.c, [self.sl["s0"]])
        mailer.classify_inbound(self.c, "head0@bo.sl", "Re: hello", "Please stop emailing us")
        self.assertTrue(mailer.is_suppressed(self.c, "head0@bo.sl"))
        self.assertEqual(self.c.execute("SELECT status FROM schools WHERE id=?", (self.sl["s0"],)).fetchone()[0],
                         "do_not_contact")
        self.assertEqual(mailer.enroll(self.c, [self.sl["s0"]])["do_not_contact"], 1)

    def test_country_template_override(self):
        server.api_templates("POST", "UG", None, {})
        server.api_templates("PUT", "UG", 1, {"subject": "Oli otya, {{school}}"})
        add_account(self.c, 1)
        acc = self.c.execute("SELECT * FROM accounts").fetchone()
        ug = self.c.execute("SELECT * FROM schools WHERE country='UG'").fetchone()
        sl = self.c.execute("SELECT * FROM schools WHERE country='SL'").fetchone()
        enr = {"person": None, "role": None, "email": "x@y.org", "thread_subject": None}
        self.assertEqual(mailer.compose(self.c, acc, ug, enr, 1)[0], "Oli otya, Gulu High")
        self.assertTrue(mailer.compose(self.c, acc, sl, enr, 1)[0].startswith("A free Bible library"))

    def test_forecast(self):
        add_account(self.c, 1, warmup=1, warmup_start=2, warmup_step=1)
        mailer.enroll(self.c, list(self.sl.values()))
        f = mailer.forecast(self.c, MONDAY_10_GMT)
        self.assertEqual((f["first_emails"], f["remaining_emails"], f["per_day_now"]), (4, 12, 2))
        self.assertEqual(f["days_first"], 2)


class WhatsApp(unittest.TestCase):
    def test_queue_and_outcomes(self):
        c = fresh()
        _, ids = load(c, "UG", rec(id="a", name="Arua P/S", district="Arua", phones=["0772 111222"],
                                   officials=[{"name": "Mr. John Okello", "role": "Head Teacher",
                                               "source_url": "https://example.org/list"}]),
                      rec(id="b", name="Office", district="Arua", phones=["0414 123456"]))
        q = phone.queue(c, *server.build_filter({"country": "UG"}))
        self.assertEqual(q["total"], 1)  # the landline can't take WhatsApp
        row = q["rows"][0]
        self.assertTrue(row["links"]["whatsapp"].startswith("https://wa.me/256772111222?text=Good%20day%20Mr%20Okello"))
        phone.record(c, ids["a"], "sent")
        s = c.execute("SELECT * FROM schools WHERE id=?", (ids["a"],)).fetchone()
        self.assertEqual((s["status"], s["whatsapp_status"]), ("contacted", "sent"))
        self.assertEqual(phone.queue(c, *server.build_filter({"country": "UG"}))["total"], 0)
        self.assertEqual(phone.today(c), 1)
        phone.record(c, ids["a"], "wrong_number", "+256 772 111 222")
        self.assertIsNone(c.execute("SELECT mobile FROM schools WHERE id=?", (ids["a"],)).fetchone()[0])


class Api(unittest.TestCase):
    def test_summary_and_filters(self):
        c = fresh()
        load(c, "SL", rec(id="1"), rec(id="2", levels=["senior_secondary"]))
        load(c, "UG", rec(id="3", district="Gulu", levels=["upper_secondary"]))
        s = server.api_summary()
        self.assertEqual([x["total"] for x in s["countries"]], [0, 2, 1])
        self.assertEqual(server.api_schools({"level": "upper_secondary"})["total"], 2)
        self.assertEqual(server.api_schools({"level": "upper_secondary", "country": "ug"})["total"], 1)
        one = server.api_summary("SL")
        self.assertEqual(next(d for d in one["by_district"] if d["district"] == "Bo")["census"], 1132)
        self.assertIn("UG", server.api_facets("UG")["countries"][2]["code"])
        csv_ = server.api_export({"country": "UG"})
        self.assertIn("Uganda", csv_)


if __name__ == "__main__":
    unittest.main()
