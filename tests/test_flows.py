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
        self.assertIn("Only a draft or a cancelled event can be deleted", r.get_data(as_text=True))
        self.assertTrue(self.sql("SELECT 1 FROM events WHERE event_id=310 AND deleted_at IS NULL"))
        con = sqlite3.connect(self.db)
        con.execute("PRAGMA foreign_keys=ON")
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute("DELETE FROM events WHERE event_id=310")
        con.close()

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
        self.assertTrue(self.sql("""SELECT 1 FROM blocks WHERE user_id=? AND ends_at IS NULL AND lifted_at IS NULL""",
                                 (owner,)))

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

    def test_catalog_calendar_and_map_views(self):
        c = self.app.test_client()
        ev = self.sql("""SELECT event_id, title, starts_at FROM events WHERE status='published'
                         AND starts_at > datetime('now','localtime') ORDER BY starts_at LIMIT 1""")[0]
        r = c.get(f"/events?view=calendar&month={ev['starts_at'][:7]}")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"/events/{ev['event_id']}", r.get_data(as_text=True))
        r = c.get("/events?view=calendar&month=bad")
        self.assertEqual(r.status_code, 200)
        r = c.get("/events?view=map&city=1")
        self.assertEqual(r.status_code, 200)
        self.assertIn('"lat":', r.get_data(as_text=True))
        r = c.get(f"/events?date={ev['starts_at'][:10]}")
        self.assertIn(f"/events/{ev['event_id']}", r.get_data(as_text=True))

    def test_event_point_saved_and_validated(self):
        org = self.client("org@demeu.kz")
        start = datetime.now() + timedelta(days=6)
        data = {"title": "Point test event", "summary": "Checking the map point",
                "description": "We check that the map point of the meeting place is saved with the event.",
                "address": "Astana, Central Park", "direction_id": 1, "city_id": 1, "coordinator_id": 1,
                "starts_at": start.strftime("%Y-%m-%dT10:00"), "ends_at": start.strftime("%Y-%m-%dT13:00"),
                "registration_deadline": (start - timedelta(days=1)).strftime("%Y-%m-%dT10:00"),
                "max_volunteers": 10, "min_age": 16, "action": "publish", "lat": "10.5", "lng": "71.4"}
        self.post(org, "/org/events/new", data)
        self.assertFalse(self.sql("SELECT 1 FROM events WHERE title='Point test event'"))
        data.update(lat="51.152770", lng="71.436240")
        self.post(org, "/org/events/new", data)
        row = self.sql("SELECT lat, lng FROM events WHERE title='Point test event'")[0]
        self.assertAlmostEqual(row["lat"], 51.15277)
        self.assertAlmostEqual(row["lng"], 71.43624)

    def _jpeg(self):
        return io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 200 + b"\xff\xd9")

    def test_photo_report_upload_rules_and_moderation(self):
        ev = self.sql("""SELECT e.event_id FROM events e JOIN registrations r USING (event_id)
                         WHERE r.volunteer_id=1024 AND r.status='attended' AND e.status='completed'
                         ORDER BY e.starts_at DESC LIMIT 1""")[0][0]
        vol = self.client("volunteer@demeu.kz")
        before = self.sql("SELECT COUNT(*) FROM event_photos WHERE event_id=?", (ev,))[0][0]
        self.post(vol, f"/events/{ev}/photos", {"photos": [(self._jpeg(), "a.jpg"), (self._jpeg(), "b.jpg")]},
                  content_type="multipart/form-data")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM event_photos WHERE event_id=?", (ev,))[0][0], before + 2)
        self.post(vol, f"/events/{ev}/photos", {"photos": [(io.BytesIO(b"not an image"), "x.jpg")]},
                  content_type="multipart/form-data")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM event_photos WHERE event_id=?", (ev,))[0][0], before + 2)
        uid = self.sql("SELECT user_id FROM volunteers WHERE volunteer_id=1024")[0][0]
        have = self.sql("SELECT COUNT(*) FROM event_photos WHERE event_id=? AND user_id=?", (ev, uid))[0][0]
        self.post(vol, f"/events/{ev}/photos", {"photos": [(self._jpeg(), f"{i}.jpg") for i in range(11 - have)]},
                  content_type="multipart/form-data")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM event_photos WHERE event_id=? AND user_id=?", (ev, uid))[0][0], have)
        future = self.sql("""SELECT event_id FROM events WHERE status='published' AND starts_at > datetime('now','localtime')
                             LIMIT 1""")[0][0]
        self.post(vol, f"/events/{future}/photos", {"photos": [(self._jpeg(), "c.jpg")]}, content_type="multipart/form-data")
        self.assertFalse(self.sql("SELECT 1 FROM event_photos WHERE event_id=?", (future,)))
        photo = self.sql("SELECT photo_id, file_path FROM event_photos WHERE event_id=? AND user_id=? ORDER BY photo_id DESC",
                         (ev, uid))[0]
        name = photo["file_path"].split("/")[1]
        anon = self.app.test_client()
        self.assertEqual(anon.get(f"/media/photos/{name}").status_code, 200)
        other = self.sql("""SELECT u.email FROM registrations r JOIN volunteers v USING (volunteer_id) JOIN users u USING (user_id)
                            WHERE r.event_id=? AND v.volunteer_id<>1024 AND u.is_active=1 LIMIT 1""", (ev,))[0][0]
        self.post(self.client(other), f"/photos/{photo['photo_id']}/report", {"reason": "unsafe"})
        self.assertTrue(self.sql("SELECT 1 FROM photo_reports WHERE photo_id=? AND status='new'", (photo["photo_id"],)))
        admin = self.client("admin@demeu.kz")
        self.post(admin, "/admin/photos", {"photo_id": photo["photo_id"], "action": "hide", "reason": "children"})
        self.assertEqual(self.sql("SELECT status FROM event_photos WHERE photo_id=?", (photo["photo_id"],))[0][0], "hidden")
        self.assertFalse(self.sql("SELECT 1 FROM photo_reports WHERE photo_id=? AND status='new'", (photo["photo_id"],)))
        self.assertEqual(anon.get(f"/media/photos/{name}").status_code, 404)
        self.assertNotIn(name, anon.get(f"/events/{ev}").get_data(as_text=True))
        for (pid,) in self.sql("SELECT photo_id FROM event_photos WHERE event_id=? AND user_id=?", (ev, uid)):
            self.post(vol, f"/photos/{pid}/delete")
        self.assertFalse(self.sql("SELECT 1 FROM event_photos WHERE event_id=? AND user_id=?", (ev, uid)))

    def test_announcement_audience_dismiss_and_notify(self):
        admin = self.client("admin@demeu.kz")
        now = datetime.now()
        before = self.sql("SELECT COUNT(*) FROM notifications WHERE kind='n_announcement'")[0][0]
        self.post(admin, "/admin/announcements", {
            "text_en": "Coordinators test banner", "text_ru": "Тестовый баннер координаторам",
            "text_kk": "Үйлестірушілерге тест баннер", "tone": "info", "audience": "coordinators",
            "starts_at": (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M"),
            "ends_at": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"), "notify": "1"})
        coords = self.sql("SELECT COUNT(*) FROM users WHERE role='coordinator' AND is_active=1")[0][0]
        self.assertEqual(self.sql("SELECT COUNT(*) FROM notifications WHERE kind='n_announcement'")[0][0], before + coords)
        self.assertNotIn("Coordinators test banner", self.client("volunteer@demeu.kz").get("/").get_data(as_text=True))
        org = self.client("org@demeu.kz")
        self.assertIn("Coordinators test banner", org.get("/").get_data(as_text=True))
        aid = self.sql("SELECT announcement_id FROM announcements WHERE text_en='Coordinators test banner'")[0][0]
        self.post(org, f"/announcements/{aid}/hide")
        self.assertNotIn("Coordinators test banner", org.get("/").get_data(as_text=True))
        self.assertNotIn("Coordinators test banner", self.client("org@demeu.kz").get("/").get_data(as_text=True))
        self.post(admin, "/admin/announcements", {"end_id": aid})
        self.assertNotIn("Coordinators test banner", self.client("org@demeu.kz").get("/").get_data(as_text=True))

    def test_duplicate_and_weekly_series(self):
        org = self.client("org@demeu.kz")
        src = self.sql("""SELECT e.* FROM events e WHERE e.org_id=1 AND e.status='completed'
                          AND EXISTS (SELECT 1 FROM registrations r WHERE r.event_id=e.event_id) ORDER BY e.starts_at DESC LIMIT 1""")[0]
        start = (datetime.now() + timedelta(days=9)).replace(hour=10, minute=0)
        before = self.sql("SELECT MAX(event_id) FROM events")[0][0]
        self.post(org, f"/org/events/{src['event_id']}/repeat", {"starts_at": start.strftime("%Y-%m-%dT%H:%M"), "mode": "once"})
        copy = self.sql("SELECT * FROM events WHERE event_id > ? ORDER BY event_id", (before,))
        self.assertEqual(len(copy), 1)
        self.assertEqual(copy[0]["status"], "draft")
        self.assertEqual(copy[0]["title"], src["title"])
        self.assertEqual(copy[0]["starts_at"], start.strftime("%Y-%m-%d %H:%M"))
        self.assertFalse(self.sql("SELECT 1 FROM registrations WHERE event_id=?", (copy[0]["event_id"],)))
        self.post(org, f"/org/events/{src['event_id']}/repeat",
                  {"starts_at": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"), "mode": "once"})
        self.assertEqual(self.sql("SELECT COUNT(*) FROM events WHERE event_id > ?", (before,))[0][0], 1)
        before = self.sql("SELECT MAX(event_id) FROM events")[0][0]
        self.post(org, f"/org/events/{src['event_id']}/repeat",
                  {"starts_at": start.strftime("%Y-%m-%dT%H:%M"), "mode": "weekly", "count": "3"})
        series = self.sql("SELECT * FROM events WHERE event_id > ? ORDER BY starts_at", (before,))
        self.assertEqual(len(series), 3)
        sid = series[0]["series_id"]
        self.assertTrue(sid)
        self.assertTrue(all(e["series_id"] == sid and e["status"] == "published" for e in series))
        gap = datetime.strptime(series[1]["starts_at"], "%Y-%m-%d %H:%M") - datetime.strptime(series[0]["starts_at"], "%Y-%m-%d %H:%M")
        self.assertEqual(gap, timedelta(days=7))
        self.post(org, f"/org/events/{series[1]['event_id']}/cancel-series", {"reason": "The embankment is closed for repairs"})
        self.assertEqual({r[0] for r in self.sql("SELECT status FROM events WHERE event_id > ?", (before,))}, {"cancelled"})
        self.assertEqual(self.sql("SELECT status FROM events WHERE event_id=?", (src["event_id"],))[0][0], "completed")

    def test_feedback_on_volunteer(self):
        reg = self.sql("""SELECT r.registration_id, r.volunteer_id FROM registrations r JOIN events e USING (event_id)
                          WHERE e.org_id=1 AND r.status='attended'
                          AND NOT EXISTS (SELECT 1 FROM volunteer_feedback f WHERE f.registration_id=r.registration_id)
                          LIMIT 1""")[0]
        org = self.client("org@demeu.kz")
        self.post(org, f"/org/registrations/{reg['registration_id']}/feedback", {})
        self.assertFalse(self.sql("SELECT 1 FROM volunteer_feedback WHERE registration_id=?", (reg["registration_id"],)))
        self.post(org, f"/org/registrations/{reg['registration_id']}/feedback",
                  {"tags": ["is_thanks", "is_reliable"], "comment": "Helped with the registration desk."})
        f = self.sql("SELECT * FROM volunteer_feedback WHERE registration_id=?", (reg["registration_id"],))[0]
        self.assertEqual((f["is_thanks"], f["is_reliable"], f["good_with_children"]), (1, 1, 0))
        uid = self.sql("SELECT user_id FROM volunteers WHERE volunteer_id=?", (reg["volunteer_id"],))[0][0]
        self.assertTrue(self.sql("SELECT 1 FROM notifications WHERE user_id=? AND kind='n_feedback_thanks'", (uid,)))
        other = self.sql("""SELECT r.registration_id FROM registrations r JOIN events e USING (event_id)
                            WHERE e.org_id<>1 AND r.status='attended' LIMIT 1""")[0][0]
        self.post(org, f"/org/registrations/{other}/feedback", {"tags": ["is_thanks"]})
        self.assertFalse(self.sql("SELECT 1 FROM volunteer_feedback WHERE registration_id=? AND updated_at IS NOT NULL", (other,)))
        pending = self.sql("""SELECT r.registration_id FROM registrations r JOIN events e USING (event_id)
                              WHERE e.org_id=1 AND r.status='pending' LIMIT 1""")[0][0]
        self.post(org, f"/org/registrations/{pending}/feedback", {"tags": ["is_thanks"]})
        self.assertFalse(self.sql("SELECT 1 FROM volunteer_feedback WHERE registration_id=?", (pending,)))
        page = self.app.test_client().get(f"/volunteers/{reg['volunteer_id']}").get_data(as_text=True)
        if self.sql("SELECT is_public FROM volunteers WHERE volunteer_id=?", (reg["volunteer_id"],))[0][0]:
            self.assertIn("Helped with the registration desk.", page)

    def test_download_my_data(self):
        r = self.client("volunteer@demeu.kz").get("/settings/my-data.json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r.headers["Content-Disposition"])
        data = json.loads(r.get_data(as_text=True))
        self.assertEqual(data["account"]["email"], "volunteer@demeu.kz")
        self.assertNotIn("password_hash", data["account"])
        self.assertEqual(data["profile"]["full_name"], "Aruzhan Kassymova")
        self.assertTrue(data["applications"] and data["certificates"] and data["feedback_from_organizations"])
        self.assertEqual(self.app.test_client().get("/settings/my-data.json").status_code, 302)

    def test_delete_account_anonymizes(self):
        uid, vid = self.sql("SELECT u.user_id, v.volunteer_id FROM users u JOIN volunteers v USING (user_id) WHERE u.email='timur@demeu.kz'")[0]
        hours_before = self.sql("SELECT SUM(hours_confirmed) FROM registrations WHERE status='attended'")[0][0]
        attended_before = self.sql("SELECT COUNT(*) FROM registrations WHERE volunteer_id=? AND status='attended'", (vid,))[0][0]
        self.assertTrue(attended_before)
        code = self.sql("""SELECT ce.code FROM certificates ce JOIN registrations r USING (registration_id)
                           WHERE r.volunteer_id=?""", (vid,))[0][0]
        anon = self.app.test_client()
        self.assertIn("Timur Sadykov", anon.get(f"/verify?code={code}").get_data(as_text=True))
        c = self.client("timur@demeu.kz")
        self.post(c, "/settings/delete", {"password": "wrong-password"})
        self.assertEqual(self.sql("SELECT is_active FROM users WHERE user_id=?", (uid,))[0][0], 1)
        self.post(c, "/settings/delete", {"password": PW})
        u = self.sql("SELECT * FROM users WHERE user_id=?", (uid,))[0]
        v = self.sql("SELECT * FROM volunteers WHERE volunteer_id=?", (vid,))[0]
        self.assertEqual((u["is_active"], v["full_name"], v["phone"]), (0, "Deleted user", "+70000000000"))
        self.assertTrue(u["deleted_at"])
        self.assertNotEqual(u["email"], "timur@demeu.kz")
        self.assertIsNone(v["about"])
        for table in ("subscriptions", "waitlist", "volunteer_directions"):
            self.assertFalse(self.sql(f"SELECT 1 FROM {table} WHERE volunteer_id=?", (vid,)))
        self.assertFalse(self.sql("""SELECT 1 FROM registrations r JOIN events e USING (event_id) WHERE r.volunteer_id=?
                                     AND r.status IN ('pending','approved') AND e.starts_at > datetime('now','localtime')""", (vid,)))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM registrations WHERE volunteer_id=? AND status='attended'", (vid,))[0][0],
                         attended_before)
        self.assertEqual(self.sql("SELECT SUM(hours_confirmed) FROM registrations WHERE status='attended'")[0][0], hours_before)
        page = anon.get(f"/verify?code={code}").get_data(as_text=True)
        self.assertNotIn("Timur", page)
        self.assertIn("deleted their DEMEU account", page)
        self.assertEqual(anon.get(f"/volunteers/{vid}").status_code, 404)
        r = self.post(self.app.test_client(), "/login", {"email": "timur@demeu.kz", "password": PW})
        self.assertNotEqual(r.status_code, 302)

    def test_trash_event_delete_restore_and_purge(self):
        org = self.client("org@demeu.kz")
        draft = self.sql("SELECT event_id, title FROM events WHERE org_id=1 AND status='draft' AND deleted_at IS NULL")[0]
        self.post(org, f"/org/events/{draft['event_id']}/delete")
        self.assertTrue(self.sql("SELECT deleted_at FROM events WHERE event_id=?", (draft["event_id"],))[0][0])
        self.assertNotIn(draft["title"], org.get("/org/events?tab=drafts").get_data(as_text=True))
        self.assertIn(draft["title"], org.get("/org/events?tab=trash").get_data(as_text=True))
        self.assertEqual(org.get(f"/org/events/{draft['event_id']}").status_code, 404)
        self.post(org, f"/org/events/{draft['event_id']}/restore")
        self.assertIsNone(self.sql("SELECT deleted_at FROM events WHERE event_id=?", (draft["event_id"],))[0][0])
        published = self.sql("SELECT event_id FROM events WHERE org_id=1 AND status='published' LIMIT 1")[0][0]
        self.post(org, f"/org/events/{published}/delete")
        self.assertIsNone(self.sql("SELECT deleted_at FROM events WHERE event_id=?", (published,))[0][0])
        self.post(org, f"/org/events/{draft['event_id']}/delete")
        con = sqlite3.connect(self.db)
        con.execute("UPDATE events SET deleted_at=datetime('now','localtime','-31 days') WHERE event_id=?", (draft["event_id"],))
        con.commit(); con.close()
        self.client("admin@demeu.kz").get("/admin/trash")
        self.assertFalse(self.sql("SELECT 1 FROM events WHERE event_id=?", (draft["event_id"],)))

    def test_trash_organization(self):
        admin = self.client("admin@demeu.kz")
        verified = self.sql("SELECT org_id FROM organizations WHERE status='verified' LIMIT 1")[0][0]
        self.post(admin, f"/admin/organizations/{verified}/delete")
        self.assertIsNone(self.sql("SELECT deleted_at FROM organizations WHERE org_id=?", (verified,))[0][0])
        org_id, email = self.sql("""SELECT o.org_id, u.email FROM organizations o JOIN coordinators c USING (org_id)
                                    JOIN users u USING (user_id) WHERE o.status='pending' LIMIT 1""")[0]
        self.post(admin, f"/admin/organizations/{org_id}/delete")
        self.assertTrue(self.sql("SELECT deleted_at FROM organizations WHERE org_id=?", (org_id,))[0][0])
        r = self.post(self.app.test_client(), "/login", {"email": email, "password": PW}, follow_redirects=True)
        self.assertIn("Your organization was deleted", r.get_data(as_text=True))
        self.post(admin, "/admin/trash", {"kind": "organization", "item_id": org_id, "action": "restore"})
        self.assertIsNone(self.sql("SELECT deleted_at FROM organizations WHERE org_id=?", (org_id,))[0][0])
        self.post(admin, f"/admin/organizations/{org_id}/delete")
        self.post(admin, "/admin/trash", {"kind": "organization", "item_id": org_id, "action": "forever"})
        self.assertFalse(self.sql("SELECT 1 FROM organizations WHERE org_id=?", (org_id,)))
        self.assertFalse(self.sql("SELECT 1 FROM users WHERE email=?", (email,)))

    def test_review_moderation_banned_words_and_report(self):
        reg = self.sql("""SELECT r.registration_id, e.event_id FROM registrations r JOIN events e USING (event_id)
                          LEFT JOIN feedback f USING (registration_id)
                          WHERE r.volunteer_id=1024 AND r.status='attended' AND f.feedback_id IS NULL LIMIT 2""")
        vol = self.client("volunteer@demeu.kz")
        self.post(vol, f"/me/applications/{reg[0]['registration_id']}/feedback",
                  {"rating": 2, "comment": "The coordinator was a real IDIOT, nobody helped us."})
        f = self.sql("SELECT * FROM feedback WHERE registration_id=?", (reg[0]["registration_id"],))[0]
        self.assertEqual((f["status"], f["is_hidden"], f["flagged_words"]), ("pending", 1, "idiot"))
        page = self.app.test_client().get(f"/events/{reg[0]['event_id']}").get_data(as_text=True)
        self.assertNotIn("real IDIOT", page)
        self.post(vol, f"/me/applications/{reg[1]['registration_id']}/feedback", {"rating": 5, "comment": "Lovely team and good tea."})
        ok = self.sql("SELECT * FROM feedback WHERE registration_id=?", (reg[1]["registration_id"],))[0]
        self.assertEqual(ok["status"], "published")
        admin = self.client("admin@demeu.kz")
        self.post(admin, "/admin/reviews", {"feedback_id": f["feedback_id"], "action": "publish"})
        self.assertEqual(self.sql("SELECT status, is_hidden FROM feedback WHERE feedback_id=?", (f["feedback_id"],))[0][:],
                         ("published", 0))
        other = self.sql("""SELECT u.email FROM registrations r JOIN volunteers v USING (volunteer_id) JOIN users u USING (user_id)
                            WHERE r.event_id=? AND r.volunteer_id<>1024 AND u.is_active=1 LIMIT 1""", (reg[1]["event_id"],))[0][0]
        self.post(self.client(other), f"/reviews/{ok['feedback_id']}/report", {"reason": "spam"})
        self.assertTrue(self.sql("SELECT 1 FROM review_reports WHERE feedback_id=? AND status='new'", (ok["feedback_id"],)))
        self.post(vol, f"/reviews/{ok['feedback_id']}/report", {"reason": "spam"})
        self.assertEqual(self.sql("SELECT COUNT(*) FROM review_reports WHERE feedback_id=?", (ok["feedback_id"],))[0][0], 1)
        self.post(admin, "/admin/reviews", {"feedback_id": ok["feedback_id"], "action": "hide", "reason": "spam"})
        self.assertEqual(self.sql("SELECT status FROM feedback WHERE feedback_id=?", (ok["feedback_id"],))[0][0], "hidden")
        self.assertFalse(self.sql("SELECT 1 FROM review_reports WHERE feedback_id=? AND status='new'", (ok["feedback_id"],)))
        self.post(admin, "/admin/reviews?tab=words", {"word_add": "Spamword"})
        self.assertTrue(self.sql("SELECT 1 FROM banned_words WHERE word='spamword'"))

    def test_block_user_login_and_unblock(self):
        admin = self.client("admin@demeu.kz")
        self.post(admin, "/admin/blocks", {"email": "minor@demeu.kz", "duration": "7", "reason": "short"})
        self.assertFalse(self.sql("SELECT 1 FROM blocks b JOIN users u USING (user_id) WHERE u.email='minor@demeu.kz'"))
        minor = self.client("minor@demeu.kz")
        self.post(admin, "/admin/blocks", {"email": "minor@demeu.kz", "duration": "7",
                                           "reason": "Did not come to three events in a row."})
        b = self.sql("SELECT b.* FROM blocks b JOIN users u USING (user_id) WHERE u.email='minor@demeu.kz'")[0]
        self.assertTrue(b["ends_at"])
        self.assertEqual(minor.get("/me/").status_code, 302)
        r = self.post(self.app.test_client(), "/login", {"email": "minor@demeu.kz", "password": PW}, follow_redirects=True)
        self.assertIn("Did not come to three events in a row.", r.get_data(as_text=True))
        self.assertTrue(self.sql("SELECT 1 FROM outbox WHERE to_email='minor@demeu.kz' AND subject LIKE '%blocked%'"))
        self.post(admin, "/admin/blocks", {"email": "admin@demeu.kz", "duration": "forever", "reason": "Testing a self block."})
        self.assertFalse(self.sql("SELECT 1 FROM blocks b JOIN users u USING (user_id) WHERE u.email='admin@demeu.kz'"))
        self.post(admin, "/admin/blocks", {"unblock": b["block_id"]})
        r = self.post(self.app.test_client(), "/login", {"email": "minor@demeu.kz", "password": PW})
        self.assertEqual(r.status_code, 302)
        con = sqlite3.connect(self.db)
        uid = self.sql("SELECT user_id FROM users WHERE email='minor@demeu.kz'")[0][0]
        con.execute("""INSERT INTO blocks (user_id, reason, starts_at, ends_at) VALUES
                       (?, 'Old block that ended.', datetime('now','localtime','-10 days'), datetime('now','localtime','-1 days'))""", (uid,))
        con.commit(); con.close()
        r = self.post(self.app.test_client(), "/login", {"email": "minor@demeu.kz", "password": PW})
        self.assertEqual(r.status_code, 302)

    def test_suspend_org_hides_events_and_keeps_history(self):
        admin = self.client("admin@demeu.kz")
        ev = self.sql("SELECT event_id FROM events WHERE org_id=2 AND status='published' LIMIT 1")[0][0]
        self.post(admin, "/admin/organizations/2/review", {"action": "suspend", "comment": "Complaints about fake events."})
        self.assertEqual(self.app.test_client().get(f"/events/{ev}").status_code, 404)
        self.assertTrue(self.sql("SELECT 1 FROM blocks WHERE org_id=2 AND lifted_at IS NULL"))
        self.post(admin, "/admin/organizations/2/review", {"action": "restore"})
        self.assertFalse(self.sql("SELECT 1 FROM blocks WHERE org_id=2 AND lifted_at IS NULL"))
        self.assertEqual(self.app.test_client().get(f"/events/{ev}").status_code, 200)

    def test_org_report_summary(self):
        org = self.client("org@demeu.kz")
        year = datetime.now().year
        r = org.get(f"/org/reports/summary?period=year&value={year}")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("Green Steppe", html)
        self.assertIn(f"Compared with {year - 1}", html)
        hours = self.sql("""SELECT COALESCE(SUM(r.hours_confirmed),0) FROM registrations r JOIN events e USING (event_id)
                            WHERE e.org_id=1 AND r.status='attended' AND e.deleted_at IS NULL
                            AND e.status IN ('published','completed') AND strftime('%Y', e.starts_at)=?""", (str(year),))[0][0]
        self.assertIn(f'<div class="n">{int(hours) if float(hours).is_integer() else hours}</div>', html)
        self.assertEqual(org.get("/org/reports/summary?period=month&value=2099-01").status_code, 200)
        self.assertEqual(self.client("volunteer@demeu.kz").get("/org/reports/summary").status_code, 403)

    def test_good_deed_request_flow(self):
        guest = self.app.test_client()
        day = (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d")
        astana = self.sql("SELECT city_id FROM cities WHERE name_en='Astana'")[0][0]
        data = {"title": "Concert for the care home", "description": "Residents of the care home would love a small concert and tea.",
                "direction_id": self.sql("SELECT direction_id FROM directions WHERE slug='seniors'")[0][0], "city_id": astana,
                "area": "Astana, care home No. 3", "when_kind": "on", "when_date": day, "people_needed": "5",
                "contact_name": "Aliya", "contact_email": "aliya.test@example.kz", "agree": "1"}
        self.post(guest, "/good-deeds/new", dict(data, agree=""))
        self.assertFalse(self.sql("SELECT 1 FROM deed_requests WHERE contact_email='aliya.test@example.kz'"))
        self.post(guest, "/good-deeds/new", data)
        req = self.sql("SELECT * FROM deed_requests WHERE contact_email='aliya.test@example.kz'")[0]
        self.assertEqual(req["status"], "unconfirmed")
        body = self.sql("SELECT body FROM outbox WHERE to_email='aliya.test@example.kz' ORDER BY message_id DESC")[0][0]
        token = re.search(r"/good-deeds/confirm/([\w-]+)", body).group(1)
        guest.get(f"/good-deeds/confirm/{token}")
        self.assertEqual(self.sql("SELECT status FROM deed_requests WHERE request_id=?", (req["request_id"],))[0][0], "pending")
        org = self.client("org@demeu.kz")
        self.assertNotIn("Concert for the care home", org.get("/org/requests").get_data(as_text=True))
        admin = self.client("admin@demeu.kz")
        self.post(admin, "/admin/good-deeds", {"request_id": req["request_id"], "action": "approve"})
        page = org.get("/org/requests").get_data(as_text=True)
        self.assertIn("Concert for the care home", page)
        self.assertNotIn("care home No. 3", page)
        self.post(org, f"/org/requests/{req['request_id']}/take")
        req = self.sql("SELECT * FROM deed_requests WHERE request_id=?", (req["request_id"],))[0]
        self.assertEqual((req["status"], req["taken_org_id"]), ("taken", 1))
        ev = self.sql("SELECT * FROM events WHERE event_id=?", (req["event_id"],))[0]
        self.assertEqual((ev["status"], ev["title"], ev["starts_at"][:10]), ("draft", "Concert for the care home", day))
        self.assertIn("care home No. 3", org.get("/org/requests?tab=ours").get_data(as_text=True))
        other_org = self.sql("""SELECT u.email FROM coordinators c JOIN users u USING (user_id) JOIN organizations o USING (org_id)
                                WHERE o.org_id<>1 AND o.status='verified' LIMIT 1""")[0][0]
        self.post(self.client(other_org), f"/org/requests/{req['request_id']}/take")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM events WHERE title='Concert for the care home'")[0][0], 1)
        self.post(org, f"/org/requests/{req['request_id']}/release")
        self.assertEqual(self.sql("SELECT status FROM deed_requests WHERE request_id=?", (req["request_id"],))[0][0], "open")
        self.assertTrue(self.sql("SELECT deleted_at FROM events WHERE event_id=?", (ev["event_id"],))[0][0])
        self.post(org, f"/org/requests/{req['request_id']}/take")
        eid = self.sql("SELECT event_id FROM deed_requests WHERE request_id=?", (req["request_id"],))[0][0]
        con = sqlite3.connect(self.db)
        con.execute("UPDATE events SET status='published' WHERE event_id=?", (eid,))
        con.commit(); con.close()
        self.assertIn("Event published", guest.get(f"/good-deeds/s/{token}").get_data(as_text=True))
        self.assertEqual(self.sql("SELECT status FROM deed_requests WHERE request_id=?", (req["request_id"],))[0][0], "done")

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
