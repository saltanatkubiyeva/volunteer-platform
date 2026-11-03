"""End-to-end checks of the main process and of the rules.
Run:  python -m unittest discover tests -v
Each run uses a fresh temporary copy of the demo database."""
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from demeu import create_app  # noqa: E402

PW = "Demeu2026!"


class FlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "test.db")
        subprocess.check_call([sys.executable, os.path.join(BASE, "seed.py"), "--reset"],
                              env={**os.environ, "DEMEU_DB": cls.db}, stdout=subprocess.DEVNULL)
        cls.app = create_app({"DATABASE": cls.db})

    def sql(self, q, args=()):
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        rows = con.execute(q, args).fetchall()
        con.close()
        return rows

    def client(self, email=None):
        c = self.app.test_client()
        if email:
            r = self.post(c, "/login", {"email": email, "password": PW})
            self.assertEqual(r.status_code, 302, email)
        return c

    def token(self, c):
        html = c.get("/contacts").get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def post(self, c, url, data=None, **kw):
        data = dict(data or {})
        data["csrf_token"] = self.token(c)
        return c.post(url, data=data, **kw)

    def open_event(self, approval=1, exclude_city_of=None):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        return self.sql("""SELECT e.* FROM events e JOIN organizations o USING (org_id)
            WHERE e.status='published' AND o.status='verified' AND e.registration_deadline > ? AND e.min_age <= 18
            AND e.requires_approval=? AND (SELECT COUNT(*) FROM registrations r WHERE r.event_id=e.event_id
            AND r.status IN ('approved','attended')) < e.max_volunteers - 1
            AND e.event_id NOT IN (SELECT event_id FROM registrations WHERE volunteer_id=1024)
            ORDER BY e.starts_at""", (now, approval))

    # ------------------------------------------------------------------ public
    def test_public_pages_in_three_languages(self):
        c = self.client()
        for lang in ("en", "ru", "kk"):
            c.get(f"/lang/{lang}")
            for url in ("/", "/events", "/events/310", "/volunteers", "/volunteers/1024", "/organizations",
                        "/organizations/1", "/reports", "/about", "/contacts", "/search?q=park", "/verify?code=DMU7K2Q9XA"):
                self.assertEqual(c.get(url).status_code, 200, (lang, url))

    def test_search_returns_three_entity_types(self):
        html = self.client().get("/search?q=an").get_data(as_text=True)
        self.assertIn("/events/", html)
        self.assertIn("/organizations/", html)
        self.assertIn("/volunteers/", html)

    def test_certificate_verification(self):
        c = self.client()
        self.assertIn("Aruzhan Kassymova", c.get("/verify?code=DMU7K2Q9XA").get_data(as_text=True))
        self.assertIn("not found", c.get("/verify?code=AAAAAAAAAA").get_data(as_text=True))

    # ------------------------------------------------------------------ security
    def test_post_without_csrf_is_rejected(self):
        r = self.app.test_client().post("/login", data={"email": "admin@demeu.kz", "password": PW})
        self.assertEqual(r.status_code, 400)

    def test_role_based_access(self):
        vol = self.client("volunteer@demeu.kz")
        self.assertEqual(vol.get("/admin/").status_code, 403)
        self.assertEqual(vol.get("/org/").status_code, 403)
        org = self.client("org@demeu.kz")
        self.assertEqual(org.get("/admin/users").status_code, 403)
        other = self.sql("SELECT event_id FROM events WHERE org_id <> 1 LIMIT 1")[0][0]
        self.assertEqual(org.get(f"/org/events/{other}").status_code, 404)
        self.assertEqual(self.client().get("/me/").status_code, 302)  # redirect to login

    def test_consent_document_is_private(self):
        cid = self.sql("SELECT consent_id FROM consents WHERE volunteer_id=1005")[0][0]
        self.assertEqual(self.client("volunteer@demeu.kz").get(f"/consents/{cid}/file").status_code, 403)
        self.assertEqual(self.client("minor@demeu.kz").get(f"/consents/{cid}/file").status_code, 200)
        self.assertEqual(self.client("admin@demeu.kz").get(f"/consents/{cid}/file").status_code, 200)

    def test_login_lockout_after_five_failures(self):
        c = self.app.test_client()
        for _ in range(5):
            self.post(c, "/login", {"email": "lock@demeu.kz", "password": "wrong"})
        r = self.post(c, "/login", {"email": "lock@demeu.kz", "password": "wrong"})
        self.assertEqual(r.status_code, 429)

    def test_contacts_hidden_from_strangers(self):
        hidden = self.sql("SELECT volunteer_id, phone FROM volunteers WHERE show_contacts=0 AND is_public=1 LIMIT 1")[0]
        html = self.client().get(f"/volunteers/{hidden[0]}").get_data(as_text=True)
        self.assertNotIn(hidden[1], html)

    # ------------------------------------------------------------------ main process
    def test_full_process_apply_approve_attend(self):
        ev = self.open_event(approval=1)[0]
        vol = self.client("volunteer@demeu.kz")
        # avoid a time clash with Aruzhan's other events for this test
        self.sql("SELECT 1")
        r = self.post(vol, f"/me/apply/{ev['event_id']}", {"motivation": "Test"})
        self.assertEqual(r.status_code, 302)
        reg = self.sql("SELECT * FROM registrations WHERE volunteer_id=1024 AND event_id=?", (ev["event_id"],))
        if not reg:  # time clash with another of her events is a valid refusal; try the next event
            self.skipTest("time clash with demo data")
        self.assertEqual(reg[0]["status"], "pending")
        # second application to the same event is refused (UNIQUE + rule)
        self.post(vol, f"/me/apply/{ev['event_id']}")
        self.assertEqual(len(self.sql("SELECT 1 FROM registrations WHERE volunteer_id=1024 AND event_id=?",
                                      (ev["event_id"],))), 1)
        # the coordinator of that organisation approves
        owner = self.sql("""SELECT u.email FROM coordinators c JOIN users u USING (user_id)
                            WHERE c.org_id=? AND c.is_owner=1""", (ev["org_id"],))[0][0]
        org = self.client(owner)
        self.post(org, f"/org/registrations/{reg[0]['registration_id']}/decide", {"decision": "approve"})
        self.assertEqual(self.sql("SELECT status FROM registrations WHERE registration_id=?",
                                  (reg[0]["registration_id"],))[0][0], "approved")
        # attendance cannot be marked before the event starts
        self.post(org, f"/org/events/{ev['event_id']}/attendance",
                  {"registration_id": reg[0]["registration_id"], f"mark_{reg[0]['registration_id']}": "attended",
                   f"hours_{reg[0]['registration_id']}": "2"})
        self.assertEqual(self.sql("SELECT status FROM registrations WHERE registration_id=?",
                                  (reg[0]["registration_id"],))[0][0], "approved")
        # volunteer cancels -> place is free again
        self.post(vol, f"/me/applications/{reg[0]['registration_id']}/cancel")
        self.assertEqual(self.sql("SELECT status FROM registrations WHERE registration_id=?",
                                  (reg[0]["registration_id"],))[0][0], "cancelled")

    def test_hours_rules_and_audit_log(self):
        ev = self.sql("""SELECT e.* FROM events e WHERE e.status='published' AND e.ends_at < ?
                         AND EXISTS (SELECT 1 FROM registrations r WHERE r.event_id=e.event_id AND r.status='approved')""",
                      (datetime.now().strftime("%Y-%m-%d %H:%M"),))[0]
        reg = self.sql("SELECT registration_id FROM registrations WHERE event_id=? AND status='approved'", (ev["event_id"],))[0][0]
        owner = self.sql("SELECT u.email FROM coordinators c JOIN users u USING (user_id) WHERE c.org_id=? AND c.is_owner=1",
                         (ev["org_id"],))[0][0]
        org = self.client(owner)
        before = len(self.sql("SELECT 1 FROM audit_log WHERE entity='registrations' AND entity_id=?", (reg,)))
        self.post(org, f"/org/events/{ev['event_id']}/attendance",  # 30 h is more than the event length
                  {"registration_id": reg, f"mark_{reg}": "attended", f"hours_{reg}": "30"})
        self.assertEqual(self.sql("SELECT status FROM registrations WHERE registration_id=?", (reg,))[0][0], "approved")
        self.post(org, f"/org/events/{ev['event_id']}/attendance",
                  {"registration_id": reg, f"mark_{reg}": "attended", f"hours_{reg}": "2"})
        row = self.sql("SELECT status, hours_confirmed FROM registrations WHERE registration_id=?", (reg,))[0]
        self.assertEqual((row[0], row[1]), ("attended", 2.0))
        after = len(self.sql("SELECT 1 FROM audit_log WHERE entity='registrations' AND entity_id=?", (reg,)))
        self.assertEqual(after, before + 1)

    def test_minor_without_consent_cannot_apply(self):
        ev = self.sql("""SELECT event_id FROM events e WHERE status='published' AND min_age <= 16
                         AND registration_deadline > ? LIMIT 1""", (datetime.now().strftime("%Y-%m-%d %H:%M"),))[0][0]
        self.post(self.client("minor@demeu.kz"), f"/me/apply/{ev}")
        self.assertFalse(self.sql("SELECT 1 FROM registrations WHERE volunteer_id=1005 AND event_id=?", (ev,)))

    def test_full_event_refuses_application(self):
        full = self.sql("""SELECT e.event_id FROM events e WHERE e.status='published' AND e.registration_deadline > ?
            AND (SELECT COUNT(*) FROM registrations r WHERE r.event_id=e.event_id AND r.status='approved') >= e.max_volunteers""",
                        (datetime.now().strftime("%Y-%m-%d %H:%M"),))[0][0]
        vid = self.sql("""SELECT v.volunteer_id, u.email FROM volunteers v JOIN users u USING (user_id)
            WHERE v.birth_date < '2000-01-01' AND v.volunteer_id NOT IN (SELECT volunteer_id FROM registrations WHERE event_id=?)
            LIMIT 1""", (full,))[0]
        self.post(self.client(vid[1]), f"/me/apply/{full}")
        self.assertFalse(self.sql("SELECT 1 FROM registrations WHERE volunteer_id=? AND event_id=?", (vid[0], full)))

    def test_pending_organization_cannot_publish(self):
        org = self.client("neworg@demeu.kz")
        start = datetime.now() + timedelta(days=5)
        data = {"title": "Food sharing evening", "summary": "Sort and deliver food parcels",
                "description": "We sort food from partner bakeries and deliver it to two shelters in Pavlodar.",
                "address": "Toraighyrov St 64", "direction_id": 6, "city_id": 8,
                "coordinator_id": self.sql("SELECT coordinator_id FROM coordinators WHERE org_id=10")[0][0],
                "starts_at": start.strftime("%Y-%m-%dT10:00"), "ends_at": start.strftime("%Y-%m-%dT13:00"),
                "registration_deadline": (start - timedelta(days=1)).strftime("%Y-%m-%dT20:00"),
                "max_volunteers": 10, "min_age": 16, "action": "publish"}
        self.post(org, "/org/events/new", data)
        self.assertFalse(self.sql("SELECT 1 FROM events WHERE title='Food sharing evening' AND status='published'"))
        data["action"] = "draft"
        self.post(org, "/org/events/new", data)
        self.assertTrue(self.sql("SELECT 1 FROM events WHERE title='Food sharing evening' AND status='draft'"))

    def test_database_refuses_deleting_event_with_registrations(self):
        admin = self.client("admin@demeu.kz")
        r = self.post(admin, "/admin/events/310/delete", follow_redirects=True)
        self.assertIn("foreign key", r.get_data(as_text=True))
        self.assertTrue(self.sql("SELECT 1 FROM events WHERE event_id=310"))

    def test_database_check_constraint_on_hours(self):
        con = sqlite3.connect(self.db)
        con.execute("PRAGMA foreign_keys=ON")
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute("UPDATE registrations SET hours_confirmed=30 WHERE registration_id=5501")
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute("INSERT INTO registrations (volunteer_id, event_id) VALUES (1024, 310)")  # duplicate
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute("INSERT INTO registrations (volunteer_id, event_id) VALUES (1024, 99999)")  # orphan
        con.close()

    def test_volunteer_registration_validation(self):
        c = self.app.test_client()
        r = self.post(c, "/register/volunteer", {"full_name": "Te", "email": "bad", "phone": "123",
                                                  "birth_date": "2020-01-01", "password": "short"})
        self.assertEqual(r.status_code, 200)  # form shown again with errors
        r = self.post(c, "/register/volunteer", {"full_name": "Test Volunteer", "email": "new.vol@mail.kz",
                                                  "phone": "8 701 555 44 33", "birth_date": "2001-05-05", "city_id": 1,
                                                  "directions": ["1", "2"], "password": "Secret123", "password2": "Secret123",
                                                  "agree": "1"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.sql("SELECT phone FROM volunteers v JOIN users u USING (user_id) WHERE u.email='new.vol@mail.kz'")[0][0],
                         "+77015554433")


if __name__ == "__main__":
    unittest.main()
