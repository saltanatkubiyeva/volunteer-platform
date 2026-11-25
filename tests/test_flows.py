import io
import json
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
from demeu import create_app

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
        self.assertEqual(self.client().get("/me/").status_code, 302)

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

    def test_full_process_apply_approve_attend(self):
        ev = self.open_event(approval=1)[0]
        vol = self.client("volunteer@demeu.kz")
        self.sql("SELECT 1")
        r = self.post(vol, f"/me/apply/{ev['event_id']}", {"motivation": "Test"})
        self.assertEqual(r.status_code, 302)
        reg = self.sql("SELECT * FROM registrations WHERE volunteer_id=1024 AND event_id=?", (ev["event_id"],))
        if not reg:
            self.skipTest("time clash with demo data")
        self.assertEqual(reg[0]["status"], "pending")
        self.post(vol, f"/me/apply/{ev['event_id']}")
        self.assertEqual(len(self.sql("SELECT 1 FROM registrations WHERE volunteer_id=1024 AND event_id=?",
                                      (ev["event_id"],))), 1)
        owner = self.sql("""SELECT u.email FROM coordinators c JOIN users u USING (user_id)
                            WHERE c.org_id=? AND c.is_owner=1""", (ev["org_id"],))[0][0]
        org = self.client(owner)
        self.post(org, f"/org/registrations/{reg[0]['registration_id']}/decide", {"decision": "approve"})
        self.assertEqual(self.sql("SELECT status FROM registrations WHERE registration_id=?",
                                  (reg[0]["registration_id"],))[0][0], "approved")
        self.post(org, f"/org/events/{ev['event_id']}/attendance",
                  {"registration_id": reg[0]["registration_id"], f"mark_{reg[0]['registration_id']}": "attended",
                   f"hours_{reg[0]['registration_id']}": "2"})
        self.assertEqual(self.sql("SELECT status FROM registrations WHERE registration_id=?",
                                  (reg[0]["registration_id"],))[0][0], "approved")
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
        self.post(org, f"/org/events/{ev['event_id']}/attendance",
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
            con.execute("INSERT INTO registrations (volunteer_id, event_id) VALUES (1024, 310)")
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute("INSERT INTO registrations (volunteer_id, event_id) VALUES (1024, 99999)")
        con.close()

    def test_reliability_shown_to_coordinator(self):
        eid = self.sql("""SELECT event_id FROM events WHERE title='Riverbank Restoration Day' AND status='published'
                          ORDER BY starts_at DESC LIMIT 1""")[0][0]
        org = self.client("org@demeu.kz")
        org.get("/lang/en")
        html = org.get(f"/org/events/{eid}?tab=pending").get_data(as_text=True)
        self.assertIn("3 no-shows in a row", html)
        self.assertIn("No history yet", html)
        self.assertIn("row-alert", html)

    def test_reliability_view_matches_registrations(self):
        row = self.sql("SELECT * FROM volunteer_reliability WHERE volunteer_id=1024")[0]
        came = self.sql("SELECT COUNT(*) FROM registrations WHERE volunteer_id=1024 AND status='attended'")[0][0]
        missed = self.sql("SELECT COUNT(*) FROM registrations WHERE volunteer_id=1024 AND status='no_show'")[0][0]
        self.assertEqual((row["attended"], row["no_show"]), (came, missed))
        self.assertEqual(row["attendance_rate"], round(100 * came / (came + missed)))

    def test_backup_and_restore(self):
        self.assertEqual(self.client("volunteer@demeu.kz").get("/admin/backups").status_code, 403)
        admin = self.client("admin@demeu.kz")
        r = self.post(admin, "/admin/backups/create")
        self.assertEqual(r.status_code, 302)
        folder = os.path.join(self.tmp, "backups")
        name = max(f for f in os.listdir(folder) if f.endswith("_manual.db"))
        original = self.sql("SELECT name_en FROM cities WHERE city_id=1")[0][0]
        con = sqlite3.connect(self.db)
        con.execute("UPDATE cities SET name_en='Changed' WHERE city_id=1")
        con.commit()
        con.close()
        self.post(admin, "/admin/backups/restore", {"name": name})
        self.assertEqual(self.sql("SELECT name_en FROM cities WHERE city_id=1")[0][0], original)
        self.assertTrue(any(f.endswith("_beforerestore.db") for f in os.listdir(folder)))
        self.assertIn(name, admin.get("/admin/backups").get_data(as_text=True))

    def test_waitlist_gives_freed_place_to_first_in_line(self):
        eid = self.sql("SELECT event_id FROM waitlist ORDER BY joined_at LIMIT 1")[0][0]
        con = sqlite3.connect(self.db)
        con.execute("UPDATE events SET requires_approval=0 WHERE event_id=?", (eid,))
        con.commit()
        con.close()
        first = self.sql("SELECT volunteer_id FROM waitlist WHERE event_id=? ORDER BY joined_at LIMIT 1", (eid,))[0][0]
        before = self.sql("SELECT COUNT(*) FROM waitlist WHERE event_id=?", (eid,))[0][0]
        part = self.sql("""SELECT r.registration_id, u.email FROM registrations r JOIN volunteers v USING (volunteer_id)
                           JOIN users u ON u.user_id=v.user_id WHERE r.event_id=? AND r.status='approved'
                           AND v.volunteer_id NOT IN (1005) LIMIT 1""", (eid,))[0]
        vol = self.client(part["email"])
        self.post(vol, f"/me/applications/{part['registration_id']}/cancel")
        got = self.sql("SELECT status FROM registrations WHERE event_id=? AND volunteer_id=?", (eid, first))
        self.assertEqual(got[0][0], "approved")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM waitlist WHERE event_id=?", (eid,))[0][0], before - 1)
        kinds = [r[0] for r in self.sql("""SELECT n.kind FROM notifications n JOIN volunteers v ON v.user_id=n.user_id
                                           WHERE v.volunteer_id=?""", (first,))]
        self.assertIn("n_waitlist_promoted", kinds)

    def test_cannot_join_waitlist_when_places_are_free(self):
        ev = self.open_event(approval=1)[0]
        vol = self.client("volunteer@demeu.kz")
        self.post(vol, f"/me/waitlist/{ev['event_id']}")
        self.assertFalse(self.sql("SELECT 1 FROM waitlist WHERE event_id=? AND volunteer_id=1024", (ev["event_id"],)))

    def test_milestone_certificate_and_verify(self):
        vol = self.client("volunteer@demeu.kz")
        r = self.post(vol, "/me/milestones/20")
        self.assertEqual(r.status_code, 302)
        code = self.sql("SELECT code FROM certificates WHERE type='milestone' AND volunteer_id=1024 AND milestone_hours=20")[0][0]
        page = vol.get(f"/me/certificate/{code}").get_data(as_text=True)
        self.assertIn("City Park Clean-up", page)
        c = self.client()
        c.get("/lang/en")
        self.assertIn("reached 20 volunteer hours", c.get(f"/verify?code={code}").get_data(as_text=True))
        self.post(vol, "/me/milestones/100")
        self.assertFalse(self.sql("SELECT 1 FROM certificates WHERE volunteer_id=1024 AND milestone_hours=100"))

    def test_subscribers_get_notified_about_new_event(self):
        from demeu import services as S
        ev = self.sql("""SELECT e.* FROM events e JOIN directions d USING (direction_id) JOIN cities c USING (city_id)
                         WHERE d.slug='ecology' AND c.name_en='Astana' AND e.org_id=1 LIMIT 1""")[0]
        con = sqlite3.connect(self.db)
        start = (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d 10:00")
        end = (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d 13:00")
        new_id = con.execute("""INSERT INTO events (title, summary, description, address, direction_id, city_id, coordinator_id,
            starts_at, ends_at, registration_deadline, max_volunteers, min_age, requires_approval, org_id, status)
            VALUES ('Subscription test', 's', 'd', 'a', ?, ?, ?, ?, ?, ?, 10, 16, 1, 1, 'published')""",
                             (ev["direction_id"], ev["city_id"], ev["coordinator_id"], start, end, start)).lastrowid
        con.commit()
        con.close()
        with self.app.test_request_context():
            self.assertGreaterEqual(S.notify_subscribers(new_id), 1)
        rows = self.sql("""SELECT n.params FROM notifications n JOIN volunteers v ON v.user_id=n.user_id
                           WHERE v.volunteer_id=1024 AND n.kind='n_new_for_you'""")
        self.assertTrue(any("Subscription test" in r[0] for r in rows))

    def test_team_leader_sees_group_phones(self):
        rid, eid = self.sql("SELECT registration_id, event_id FROM registrations WHERE volunteer_id=1024 AND is_team_lead=1")[0]
        vol = self.client("volunteer@demeu.kz")
        vol.get("/lang/en")
        html = vol.get(f"/events/{eid}").get_data(as_text=True)
        self.assertIn("You are the team leader of this event", html)
        other = self.sql("""SELECT r.registration_id FROM registrations r WHERE r.event_id=? AND r.status='approved'
                            AND r.volunteer_id<>1024 LIMIT 1""", (eid,))[0][0]
        org = self.client("org@demeu.kz")
        self.post(org, f"/org/registrations/{other}/team-lead", {"on": "1"})
        self.assertEqual(self.sql("SELECT is_team_lead FROM registrations WHERE registration_id=?", (other,))[0][0], 1)

    def test_shift_preference_and_assignment(self):
        eid = self.sql("SELECT event_id FROM event_shifts WHERE title='Clearing the riverbank'")[0][0]
        org = self.client("org@demeu.kz")
        html = org.get(f"/org/events/{eid}?tab=participants&propose=1").get_data(as_text=True)
        self.assertIn("proposed", html)
        picks = dict(re.findall(r'name="shift_(\d+)" form="shifts-form">.*?<option value="([^"]*)" selected', html, re.S))
        self.assertTrue(picks)
        self.post(org, f"/org/events/{eid}/shifts", {f"shift_{k}": v for k, v in picks.items()})
        need = {r["shift_id"]: r["max_volunteers"] for r in self.sql("SELECT * FROM event_shifts WHERE event_id=?", (eid,))}
        for sid, cap in need.items():
            n = self.sql("""SELECT COUNT(*) FROM registrations WHERE event_id=? AND status IN ('approved','attended')
                            AND (shift_id=? OR all_shifts=1)""", (eid, sid))[0][0]
            self.assertLessEqual(n, cap)
        wished = self.sql("""SELECT COUNT(*) FROM registrations WHERE event_id=? AND status='approved'
                             AND preferred_shift_id IS NOT NULL AND shift_id = preferred_shift_id""", (eid,))[0][0]
        self.assertGreater(wished, 0)
        self.assertTrue(self.sql("SELECT 1 FROM notifications WHERE kind IN ('n_shift_assigned','n_shift_all')"))

    def test_apply_with_preferred_shift(self):
        eid = self.sql("SELECT event_id FROM event_shifts WHERE title='Info points and navigation'")[0][0]
        sid = self.sql("SELECT shift_id FROM event_shifts WHERE event_id=? ORDER BY position LIMIT 1", (eid,))[0][0]
        row = self.sql("""SELECT u.email, v.volunteer_id FROM volunteers v JOIN users u ON u.user_id=v.user_id
            WHERE v.birth_date <= date('now','-18 years') AND v.volunteer_id NOT IN
            (SELECT volunteer_id FROM registrations WHERE event_id=?) AND v.volunteer_id NOT IN
            (SELECT r.volunteer_id FROM registrations r JOIN events e USING (event_id) WHERE r.status IN ('pending','approved')
             AND e.starts_at < (SELECT ends_at FROM events WHERE event_id=?) AND e.ends_at > (SELECT starts_at FROM events WHERE event_id=?))
            AND v.volunteer_id NOT IN (SELECT volunteer_id FROM waitlist) LIMIT 1""", (eid, eid, eid))[0]
        vol = self.client(row["email"])
        self.post(vol, f"/me/apply/{eid}", {"shift_pref": str(sid)})
        got = self.sql("SELECT preferred_shift_id, prefers_all_shifts FROM registrations WHERE event_id=? AND volunteer_id=?",
                       (eid, row["volunteer_id"]))[0]
        self.assertEqual((got[0], got[1]), (sid, 0))

    def test_password_reset_by_link(self):
        email = self.sql("SELECT u.email FROM users u JOIN volunteers v USING (user_id) WHERE v.volunteer_id=1030")[0][0]
        c = self.client()
        c.get("/lang/en")
        html = self.post(c, "/forgot", {"email": email}).get_data(as_text=True)
        self.assertIn("We sent a link to " + email[0] + "****" + email.split("@")[0][-1] + "@" + email.split("@")[1], html)
        self.assertIn("No account with this email", self.post(c, "/forgot", {"email": "nobody@nowhere.kz"}).get_data(as_text=True))
        link = self.sql("SELECT link FROM outbox WHERE to_email=? ORDER BY message_id DESC LIMIT 1", (email,))[0][0]
        token = link.rsplit("/", 1)[1]
        stored = self.sql("SELECT token_hash FROM password_resets ORDER BY reset_id DESC LIMIT 1")[0][0]
        self.assertNotEqual(stored, token)
        path = "/reset/" + token
        self.assertEqual(c.get(path).status_code, 200)
        self.post(c, path, {"password": "NewPass2026", "password2": "NewPass2026"})
        r = self.post(self.app.test_client(), "/login", {"email": email, "password": "NewPass2026"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(c.get(path).status_code, 410)
        con = sqlite3.connect(self.db)
        con.execute("UPDATE password_resets SET used_at=NULL, expires_at='2000-01-01 00:00:00', created_at='1999-01-01 00:00:00'")
        con.commit()
        con.close()
        self.assertEqual(c.get(path).status_code, 410)

    def test_report_event_and_admin_resolves(self):
        eid = self.sql("SELECT event_id FROM complaints WHERE status='new' AND event_id IS NOT NULL LIMIT 1")[0][0]
        vol = self.client("volunteer@demeu.kz")
        self.post(vol, "/report", {"event_id": eid, "reason": "other", "details": "short"})
        self.assertFalse(self.sql("SELECT 1 FROM complaints c JOIN users u ON u.user_id=c.reporter_id WHERE u.email='volunteer@demeu.kz'"))
        self.post(vol, "/report", {"event_id": eid, "reason": "unsafe", "details": "No safety briefing announced."})
        self.post(vol, "/report", {"event_id": eid, "reason": "unsafe", "details": "Second time."})
        mine = self.sql("""SELECT COUNT(*) FROM complaints c JOIN users u ON u.user_id=c.reporter_id
                           WHERE u.email='volunteer@demeu.kz' AND c.event_id=?""", (eid,))[0][0]
        self.assertEqual(mine, 1)
        org = self.client("org@demeu.kz")
        own_event = self.sql("SELECT event_id FROM events WHERE org_id=1 AND status='published' LIMIT 1")[0][0]
        self.post(org, "/report", {"event_id": own_event, "reason": "fake"})
        self.assertFalse(self.sql("SELECT 1 FROM complaints WHERE event_id=?", (own_event,)))
        admin = self.client("admin@demeu.kz")
        self.assertEqual(admin.get("/admin/complaints").status_code, 200)
        self.assertEqual(admin.get("/admin/complaints?tab=handled").status_code, 200)
        cid = self.sql("SELECT complaint_id FROM complaints WHERE event_id=? AND status='new' LIMIT 1", (eid,))[0][0]
        open_before = self.sql("SELECT COUNT(*) FROM complaints WHERE event_id=? AND status='new'", (eid,))[0][0]
        self.post(admin, f"/admin/complaints/{cid}", {"decision": "resolved", "action": "event_cancelled",
                                                      "note": "Payment for participation is not allowed."})
        self.assertEqual(self.sql("SELECT status FROM events WHERE event_id=?", (eid,))[0][0], "cancelled")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM complaints WHERE event_id=? AND status='resolved'", (eid,))[0][0],
                         open_before)
        self.assertTrue(self.sql("SELECT 1 FROM notifications WHERE kind='n_report_resolved'"))

    def test_block_account_from_report(self):
        oid = self.sql("SELECT org_id FROM complaints WHERE status='new' AND org_id IS NOT NULL LIMIT 1")[0][0]
        cid = self.sql("SELECT complaint_id FROM complaints WHERE org_id=? AND status='new'", (oid,))[0][0]
        owner = self.sql("""SELECT u.user_id FROM coordinators c JOIN users u USING (user_id) WHERE c.org_id=?
                            ORDER BY c.is_owner DESC LIMIT 1""", (oid,))[0][0]
        admin = self.client("admin@demeu.kz")
        self.post(admin, f"/admin/complaints/{cid}", {"decision": "resolved", "action": "account_blocked", "note": "x"})
        self.assertEqual(self.sql("SELECT status FROM complaints WHERE complaint_id=?", (cid,))[0][0], "new")
        self.post(admin, f"/admin/complaints/{cid}", {"decision": "resolved", "action": "account_blocked",
                                                      "note": "Advertising after a warning."})
        self.assertEqual(self.sql("SELECT is_active FROM users WHERE user_id=?", (owner,))[0][0], 0)
    def test_required_documents_flow(self):
        eid = self.sql("SELECT event_id FROM events WHERE title='Food Parcel Delivery to Families'")[0][0]
        vol = self.client("volunteer@demeu.kz")
        self.post(vol, f"/me/apply/{eid}", {"has_doc": ["1", "2"]})
        self.assertFalse(self.sql("SELECT 1 FROM registrations WHERE volunteer_id=1024 AND event_id=?", (eid,)))
        admin = self.client("admin@demeu.kz")
        self.assertEqual(admin.get("/admin/documents").status_code, 200)
        pending = [r[0] for r in self.sql("SELECT volunteer_skill_id FROM volunteer_skills WHERE volunteer_id=1024 AND status='pending'")]
        self.post(admin, "/admin/documents", {"doc_id": pending[0], "action": "reject", "comment": "x"})
        self.assertEqual(self.sql("SELECT status FROM volunteer_skills WHERE volunteer_skill_id=?", (pending[0],))[0][0], "pending")
        for d in pending:
            self.post(admin, "/admin/documents", {"doc_id": d, "action": "approve"})
        self.post(vol, f"/me/apply/{eid}", {"has_doc": ["1"]})
        self.assertFalse(self.sql("SELECT 1 FROM registrations WHERE volunteer_id=1024 AND event_id=?", (eid,)))
        skills = [str(r[0]) for r in self.sql("SELECT skill_id FROM event_requirements WHERE event_id=?", (eid,))]
        self.post(vol, f"/me/apply/{eid}", {"has_doc": skills})
        self.assertTrue(self.sql("SELECT 1 FROM registrations WHERE volunteer_id=1024 AND event_id=?", (eid,)))
        doc = pending[0]
        self.assertEqual(self.client("org@demeu.kz").get(f"/documents/{doc}/file").status_code, 403)
        self.assertEqual(vol.get(f"/documents/{doc}/file").status_code, 200)

    def test_document_upload_needs_expiry(self):
        vol = self.client("minor@demeu.kz")
        sid = self.sql("SELECT skill_id FROM skills WHERE slug='driver_license'")[0][0]
        pdf = open(os.path.join(os.path.dirname(__file__), "..", "demeu", "static", "sample_document.pdf"), "rb").read()
        self.post(vol, "/me/documents", {"skill_id": sid, "document": (io.BytesIO(pdf), "doc.pdf")})
        self.assertFalse(self.sql("SELECT 1 FROM volunteer_skills WHERE volunteer_id=1005"))
        self.post(vol, "/me/documents", {"skill_id": sid, "expires_at": "2030-01-01",
                                         "document": (io.BytesIO(pdf), "doc.pdf")})
        self.assertEqual(self.sql("SELECT status FROM volunteer_skills WHERE volunteer_id=1005")[0][0], "pending")

    def test_urgent_call_once_per_day(self):
        ev = self.sql("""SELECT e.event_id, e.city_id FROM events e WHERE e.org_id=1 AND e.status='published'
                         AND e.starts_at > datetime('now','localtime') AND NOT EXISTS
                         (SELECT 1 FROM event_requirements er WHERE er.event_id=e.event_id)
                         AND e.max_volunteers > (SELECT COUNT(*) FROM registrations r WHERE r.event_id=e.event_id
                         AND r.status IN ('approved','attended')) ORDER BY e.starts_at LIMIT 1""")[0]
        org = self.client("org@demeu.kz")
        self.post(org, f"/org/events/{ev['event_id']}/urgent")
        sent = self.sql("SELECT COUNT(*) FROM notifications WHERE kind='n_urgent_call'")[0][0]
        self.assertGreater(sent, 0)
        wrong_city = self.sql("""SELECT COUNT(*) FROM notifications n JOIN volunteers v ON v.user_id=n.user_id
                                 WHERE n.kind='n_urgent_call' AND v.city_id<>?""", (ev["city_id"],))[0][0]
        self.assertEqual(wrong_city, 0)
        self.post(org, f"/org/events/{ev['event_id']}/urgent")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM notifications WHERE kind='n_urgent_call'")[0][0], sent)
        self.assertEqual(self.sql("SELECT is_urgent FROM events WHERE event_id=?", (ev["event_id"],))[0][0], 1)

    def _jpeg(self):
        return io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 200 + b"\xff\xd9")

    def test_friends_requests_and_privacy(self):
        anel_email = self.sql("SELECT u.email FROM volunteers v JOIN users u USING (user_id) WHERE v.volunteer_id=1047")[0][0]
        anel = self.client(anel_email)
        self.assertIn("Aruzhan", anel.get("/me/friends?tab=requests").get_data(as_text=True))
        fid = self.sql("SELECT friendship_id FROM friendships WHERE requester_id=1024 AND addressee_id=1047")[0][0]
        self.post(anel, f"/me/friends/{fid}/accept")
        self.assertEqual(self.sql("SELECT status FROM friendships WHERE friendship_id=?", (fid,))[0][0], "accepted")
        aru_uid = self.sql("SELECT user_id FROM volunteers WHERE volunteer_id=1024")[0][0]
        self.assertTrue(self.sql("SELECT 1 FROM notifications WHERE user_id=? AND kind='n_friend_accepted'", (aru_uid,)))
        vol = self.client("volunteer@demeu.kz")
        self.post(vol, "/me/friends/add/1041")
        self.post(vol, "/me/friends/add/1041")
        self.assertEqual(self.sql("""SELECT COUNT(*) FROM friendships WHERE (requester_id=1024 AND addressee_id=1041)
                                     OR (requester_id=1041 AND addressee_id=1024)""")[0][0], 1)
        nurs = self.client(self.sql("SELECT u.email FROM volunteers v JOIN users u USING (user_id) WHERE v.volunteer_id=1041")[0][0])
        self.post(nurs, "/me/friends/add/1024")
        self.assertEqual(self.sql("SELECT status FROM friendships WHERE requester_id=1024 AND addressee_id=1041")[0][0], "accepted")
        self.assertEqual(vol.get("/volunteers/1020").status_code, 404)
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO friendships (requester_id, addressee_id, status, accepted_at) VALUES (1020, 1024, 'accepted', datetime('now'))")
        con.commit(); con.close()
        self.assertEqual(vol.get("/volunteers/1020").status_code, 200)
        self.assertEqual(self.client("minor@demeu.kz").get("/volunteers/1020").status_code, 404)

    def test_friends_going_cards_milestones_and_kudos(self):
        from demeu import friends as FR, services as S
        vol = self.client("volunteer@demeu.kz")
        page = vol.get("/events").get_data(as_text=True)
        self.assertIn("2 friends going", page)
        con = sqlite3.connect(self.db)
        con.execute("UPDATE volunteers SET share_plans=0 WHERE volunteer_id=1011")
        con.commit(); con.close()
        self.assertIn("Ramazan is going", vol.get("/events").get_data(as_text=True))
        aru_uid = self.sql("SELECT user_id FROM volunteers WHERE volunteer_id=1024")[0][0]
        with self.app.test_request_context():
            aru = self.sql("SELECT * FROM volunteers WHERE volunteer_id=1024")[0]
            target = None
            for ev in self.open_event(0):
                full = S.get_event(ev["event_id"])
                if not S.eligibility(dict(aru), full) and not self.sql(
                        "SELECT 1 FROM registrations WHERE volunteer_id=1022 AND event_id=?", (ev["event_id"],)):
                    target = ev["event_id"]
                    break
            if target is None:
                self.skipTest("no event for the demo volunteer")
            from demeu.db import execute
            execute("INSERT INTO registrations (volunteer_id, event_id, status, decided_at) VALUES (1022, ?, 'approved', datetime('now'))", (target,))
            FR.on_joined(1022, target)
            FR.on_joined(1022, target)
            FR.on_hours(1022, 45, 52)
            from demeu.db import get_db
            get_db().commit()
        self.assertEqual(self.sql("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='n_friend_going' AND link=?",
                                  (aru_uid, f"/events/{target}"))[0][0], 1)
        self.assertTrue(self.sql("SELECT 1 FROM notifications WHERE user_id=? AND kind='n_friend_milestone' AND params LIKE '%50%'", (aru_uid,)))
        self.post(vol, "/me/friends/kudos", {"volunteer_id": 1022, "n": 50})
        self.post(vol, "/me/friends/kudos", {"volunteer_id": 1022, "n": 50})
        self.assertEqual(self.sql("SELECT COUNT(*) FROM kudos WHERE from_id=1024 AND to_id=1022 AND milestone=50")[0][0], 1)
        ram_uid = self.sql("SELECT user_id FROM volunteers WHERE volunteer_id=1022")[0][0]
        self.assertTrue(self.sql("SELECT 1 FROM notifications WHERE user_id=? AND kind='n_kudos'", (ram_uid,)))
        self.post(vol, "/me/friends/kudos", {"volunteer_id": 1046, "n": 20})
        self.assertFalse(self.sql("SELECT 1 FROM kudos WHERE to_id=1046"))
        self.assertIn("Kirill", vol.get("/me/friends?tab=friends").get_data(as_text=True))
        self.assertTrue(len(self.sql("SELECT 1 FROM friendships")) > 0)

    def test_volunteer_registration_validation(self):
        c = self.app.test_client()
        r = self.post(c, "/register/volunteer", {"full_name": "Te", "email": "bad", "phone": "123",
                                                  "birth_date": "2020-01-01", "password": "short"})
        self.assertEqual(r.status_code, 200)
        r = self.post(c, "/register/volunteer", {"full_name": "Test Volunteer", "email": "new.vol@mail.kz",
                                                  "phone": "8 701 555 44 33", "birth_date": "2001-05-05", "city_id": 1,
                                                  "directions": ["1", "2"], "password": "Secret123", "password2": "Secret123",
                                                  "agree": "1"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.sql("SELECT phone FROM volunteers v JOIN users u USING (user_id) WHERE u.email='new.vol@mail.kz'")[0][0],
                         "+77015554433")


if __name__ == "__main__":
    unittest.main()
