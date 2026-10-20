"""python3 -m unittest discover tests  —  no network, no real email."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "test-secret")

from slcrm import config, db, importer, levels, mailer, mbsse, schoollist  # noqa: E402

MONDAY_10AM = 1760954400.0  # Mon 2025-10-20 10:00 GMT


def raw(**kw):
    rec = {"name": "Test School", "kind": "school", "levels": ["primary"], "district": "Bo", "town": "Bo",
           "emails": [], "phones": [], "officials": [], "sources": ["https://example.org/list"], "worker": "t"}
    rec.update(kw)
    return rec


class Rules(unittest.TestCase):
    def test_phone(self):
        self.assertEqual(levels.clean_phone("076 123 456"), "+232 76 123 456")
        self.assertEqual(levels.clean_phone("+232-78-570129"), "+232 78 570 129")
        self.assertIsNone(levels.clean_phone("12"))

    def test_district_aliases(self):
        self.assertEqual(levels.canonical_district("Freetown"), "Western Area Urban")
        self.assertEqual(levels.canonical_district("Western Rural"), "Western Area Rural")
        self.assertEqual(levels.district_from_text("Teko Road, Makeni"), "Bombali")

    def test_merge_key_keeps_levels(self):
        self.assertNotEqual(levels.merge_key("RC Primary School"), levels.merge_key("RC Junior Secondary School"))
        self.assertEqual(levels.merge_key("R.C. J.S.S."), levels.merge_key("Roman Catholic Junior Secondary School"))

    def test_greeting(self):
        self.assertEqual(mailer.greeting("Mrs. Fatmata Kamara", "Principal"), "Dear Mrs Kamara,")
        self.assertEqual(mailer.greeting(None, "Principal"), "Dear Principal,")
        self.assertEqual(mailer.greeting(None, None), "Dear Sir or Madam,")


class Merge(unittest.TestCase):
    def run_merge(self, records):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "t.jsonl"), "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        out = tempfile.mkdtemp()
        stats = importer.merge(d, out)
        with open(os.path.join(out, "sierra-leone-schools.jsonl")) as f:
            rows = [json.loads(x) for x in f]
        return stats, rows

    def test_same_name_different_towns_stay_separate(self):
        _, rows = self.run_merge([raw(name="RC Primary School", town="Tikonko"), raw(name="R.C. Primary School", town="Gerihun")])
        self.assertEqual(len(rows), 2)

    def test_duplicates_fold_and_keep_sources(self):
        _, rows = self.run_merge([
            raw(name="Bo School", levels=["senior_secondary"], emis_code="310801404"),
            raw(name="Bo School", levels=["junior_secondary"], town=None, emails=[
                {"email": "INFO@boschool.edu.sl", "source_url": "https://boschool.edu.sl/contact", "confidence": "high"}])])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["levels"], ["junior_secondary", "senior_secondary"])
        self.assertEqual(rows[0]["emails"][0]["email"], "info@boschool.edu.sl")

    def test_reused_emis_code_with_different_name_is_not_merged(self):
        _, rows = self.run_merge([raw(name="Jos Marian School", emis_code="129103303"),
                                  raw(name="Government School", emis_code="129103303")])
        self.assertEqual(len(rows), 2)

    def test_email_without_source_is_dropped(self):
        _, rows = self.run_merge([raw(sources=["https://a.org", "https://b.org"], emails=[{"email": "x@y.org"}])])
        self.assertEqual(rows[0]["emails"], [])


class Mbsse(unittest.TestCase):
    def test_parse_schedule_table(self):
        html = """<h3>PAYMENT OF TUITION FEES TO PRIMARY SCHOOLS IN KONO DISTRICT FOR SECOND TERM</h3><table>
          <tr><th>No.</th><th>EMIS</th><th>Name Of School</th><th>Region</th><th>District</th><th>Chiefdom</th>
              <th>Address</th><th>Headcount</th></tr>
          <tr><td>1</td><td>139100001</td><td>Example Primary School</td><td>East</td><td>Kono District</td>
              <td>Gbense</td><td>Koidu</td><td>1,250</td></tr></table>"""
        rows = mbsse.parse(html, mbsse.page_district(html))
        self.assertEqual(rows, [{"emis": "139100001", "name": "Example Primary School", "district": "Kono",
                                 "chiefdom": "Gbense", "town": "Koidu", "headcount": 1250}])


class SchoolList(unittest.TestCase):
    TEXT = """emis_num   Level     Region   Council          Chfdom   School Name                         Town      phone       owner
110101206  Primary   East     Kailahun DC      1        Roman Catholic Primary School       Sienga    076484775   Mission
110101207  Primary   East     Kailahun DC      1        Community Primary School            Gbahama   79175290    Community
Page 1 of 9"""

    def test_parse_rows(self):
        rows = schoollist.parse(self.TEXT)
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]["name"], rows[0]["town"], rows[0]["district"], rows[0]["phone"], rows[0]["owner"]),
                         ("Roman Catholic Primary School", "Sienga", "Kailahun", "+232 76 484 775", "mission"))
        self.assertEqual(rows[1]["phone"], "+232 79 175 290")

    def test_ingest_matches_by_emis_and_adds_phone(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        tmp = Path(tempfile.mkdtemp())
        c = db.connect(path)
        t = db.now()
        c.execute("INSERT INTO schools(name, norm, levels, district, emis_code, created_at, updated_at) "
                  "VALUES ('R.C. Primary School Sienga', 'rc primary school sienga', 2, 'Kailahun', '110101206', ?, ?)",
                  (t, t))
        old_cache, old_text = config.CACHE, schoollist.pdf_text
        config.CACHE, schoollist.pdf_text = tmp, lambda p: self.TEXT
        try:
            (tmp / "list.pdf").write_bytes(b"%PDF")
            st = schoollist.ingest(c, urls=["https://example.org/list.pdf"], out=tmp / "out.jsonl")
        finally:
            config.CACHE, schoollist.pdf_text = old_cache, old_text
        self.assertEqual((st["rows"], st["matched"], st["added"], st["with_phone"]), (2, 1, 1, 2))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM schools").fetchone()[0], 2)
        self.assertEqual(c.execute("SELECT phone FROM schools WHERE emis_code='110101206'").fetchone()[0],
                         "+232 76 484 775")
        self.assertEqual(len((tmp / "out.jsonl").read_text().splitlines()), 2)
        c.close()
        os.unlink(path)


class Mailer(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.c = db.connect(self.path)
        t = db.now()
        for i, (name, email) in enumerate([("Alpha School", "head@alpha.edu.sl"), ("Beta School", "office@beta.edu.sl"),
                                           ("Gamma School", None)], 1):
            self.c.execute("INSERT INTO schools(id, name, norm, levels, district, created_at, updated_at) "
                           "VALUES (?,?,?,?,?,?,?)", (i, name, name.lower(), 2, "Bo", t, t))
            if email:
                db.upsert_contact(self.c, i, "email", email, "research", confidence="high")
            db.refresh_primary(self.c, i)
        self.c.execute("INSERT INTO accounts(id, label, from_name, from_email, smtp_host, smtp_port, username, "
                       "password_enc, daily_cap, hourly_cap, min_gap_s, warmup, warmup_start, created_at) "
                       "VALUES (1,'A','Ashish','a@example.org','smtp.example.org',587,'a@example.org',?,40,10,60,1,2,?)",
                       (mailer.encrypt("app-pass"), t))
        db.set_meta(self.c, "sending", "1")
        self.sent = []

    def tearDown(self):
        self.c.close()
        os.unlink(self.path)

    def send(self, acc, msg):
        self.sent.append(msg)

    def test_password_roundtrip_and_never_exposed(self):
        acc = self.c.execute("SELECT * FROM accounts WHERE id=1").fetchone()
        self.assertEqual(mailer.account_password(acc), "app-pass")
        pub = mailer.public_account(acc)
        self.assertNotIn("password_enc", pub)
        self.assertTrue(pub["has_password"])

    def test_sequence_limits_and_follow_up_threading(self):
        stats = mailer.enroll(self.c, [1, 2, 3], t=MONDAY_10AM - 10)
        self.assertEqual(stats["enrolled"], 2)
        self.assertEqual(stats["no_email"], 1)
        mailer.tick(self.c, self.send, t=MONDAY_10AM)
        self.assertEqual(len(self.sent), 1)
        mailer.tick(self.c, self.send, t=MONDAY_10AM + 30)  # inside the minimum gap
        self.assertEqual(len(self.sent), 1)
        mailer.tick(self.c, self.send, t=MONDAY_10AM + 200)
        self.assertEqual(len(self.sent), 2)
        mailer.tick(self.c, self.send, t=MONDAY_10AM + 400)  # warm-up cap of 2 on day one
        self.assertEqual(len(self.sent), 2)
        first = self.sent[0]
        self.assertIn("List-Unsubscribe", first)
        self.assertIn("unsubscribe", first.get_content().lower())
        # Email 2 waits four days, then replies in the same thread.
        later = MONDAY_10AM + 4 * 86400 + 60
        mailer.tick(self.c, self.send, t=later)
        follow = self.sent[2]
        self.assertTrue(follow["Subject"].startswith("Re: "))
        self.assertIn(follow["In-Reply-To"], (first["Message-ID"], self.sent[1]["Message-ID"]))

    def test_weekend_and_hours(self):
        mailer.enroll(self.c, [1], t=MONDAY_10AM - 10)
        mailer.tick(self.c, self.send, t=MONDAY_10AM - 5 * 3600)  # 05:00
        mailer.tick(self.c, self.send, t=MONDAY_10AM - 2 * 86400)  # Saturday
        self.assertEqual(self.sent, [])

    def test_sending_switch(self):
        db.set_meta(self.c, "sending", "0")
        mailer.enroll(self.c, [1], t=MONDAY_10AM - 10)
        mailer.tick(self.c, self.send, t=MONDAY_10AM)
        self.assertEqual(self.sent, [])

    def test_unsubscribe_reply_and_bounce(self):
        mailer.enroll(self.c, [1, 2], t=MONDAY_10AM - 10)
        mailer.classify_inbound(self.c, "head@alpha.edu.sl", "Re: A free Bible library", "Please unsubscribe me")
        mailer.classify_inbound(self.c, "MAILER-DAEMON@mx.example.org", "Undelivered Mail",
                                "Final-Recipient: rfc822; office@beta.edu.sl")
        self.assertTrue(mailer.is_suppressed(self.c, "head@alpha.edu.sl"))
        self.assertTrue(mailer.is_suppressed(self.c, "office@beta.edu.sl"))
        mailer.tick(self.c, self.send, t=MONDAY_10AM)
        self.assertEqual(self.sent, [])
        self.assertEqual(mailer.enroll(self.c, [1], t=MONDAY_10AM)["enrolled"], 0)

    def test_reply_stops_sequence(self):
        mailer.enroll(self.c, [1], t=MONDAY_10AM - 10)
        res = mailer.classify_inbound(self.c, "head@alpha.edu.sl", "Re: library", "Yes, we'd love it.")
        self.assertEqual(res[0], "replied")
        self.assertEqual(self.c.execute("SELECT status FROM schools WHERE id=1").fetchone()[0], "replied")

    def test_unsubscribe_link_token(self):
        old = config.PUBLIC_URL
        config.PUBLIC_URL = "https://crm.example.org"
        try:
            url = mailer.unsub_url("Head@Alpha.edu.sl")
        finally:
            config.PUBLIC_URL = old
        from urllib.parse import parse_qs, urlsplit
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        self.assertEqual(mailer.decode_unsub(q["e"], q["t"]), "head@alpha.edu.sl")
        self.assertIsNone(mailer.decode_unsub(q["e"], "0" * 24))

    def test_auth_failure_pauses_account(self):
        import smtplib

        def bad(acc, msg):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        mailer.enroll(self.c, [1], t=MONDAY_10AM - 10)
        mailer.tick(self.c, bad, t=MONDAY_10AM)
        self.assertEqual(self.c.execute("SELECT enabled FROM accounts WHERE id=1").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
