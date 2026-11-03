"""Business rules of the main process: a volunteer applies -> the coordinator decides ->
the volunteer attends -> the coordinator confirms hours -> certificate & feedback."""
import secrets
import string
from datetime import datetime

from flask import url_for

from .core import age_on, audit, duration_hours, notify, now_str, parse_dt
from .db import execute, query, scalar, transaction

ACTIVE = ("pending", "approved")
MILESTONES = (10, 20, 50, 100, 200)

EVENT_SELECT = """
SELECT e.*,
       o.name AS org_name, o.logo_path AS org_logo, o.status AS org_status,
       d.slug AS dir_slug, d.name_en AS dir_name_en, d.name_ru AS dir_name_ru,
       d.name_kk AS dir_name_kk, d.icon AS dir_icon, d.tone AS dir_tone,
       c.name_en AS city_name_en, c.name_ru AS city_name_ru, c.name_kk AS city_name_kk,
       (SELECT COUNT(*) FROM registrations r
         WHERE r.event_id = e.event_id AND r.status IN ('approved','attended')) AS taken,
       (SELECT COUNT(*) FROM registrations r
         WHERE r.event_id = e.event_id AND r.status = 'pending') AS pending
FROM events e
JOIN organizations o ON o.org_id = e.org_id
JOIN directions d    ON d.direction_id = e.direction_id
JOIN cities c        ON c.city_id = e.city_id
"""

# Events that anyone may see: published or completed, by a verified organisation
PUBLIC_WHERE = "e.status IN ('published','completed') AND o.status = 'verified'"


def get_event(event_id):
    return query(EVENT_SELECT + " WHERE e.event_id = ?", (event_id,), one=True)


class RuleError(Exception):
    """Raised with a translation key when a business rule blocks an action."""

    def __init__(self, key, **params):
        super().__init__(key)
        self.key = key
        self.params = params


def consent_status(volunteer_id):
    row = query("SELECT status FROM consents WHERE volunteer_id=? ORDER BY consent_id DESC LIMIT 1",
                (volunteer_id,), one=True)
    return row["status"] if row else None


def eligibility(volunteer, ev):
    """Why this volunteer cannot apply right now (translation key) or None."""
    now = now_str()
    if ev["status"] != "published" or ev["org_status"] != "verified":
        return "rule_not_open"
    if ev["starts_at"] <= now:
        return "rule_started"
    if ev["registration_deadline"] < now:
        return "rule_deadline"
    age = age_on(volunteer["birth_date"], parse_dt(ev["starts_at"]))
    if age is not None and age < ev["min_age"]:
        return "rule_min_age"
    if age is not None and age < 18 and consent_status(volunteer["volunteer_id"]) != "approved":
        return "rule_consent"
    reg = query("SELECT status FROM registrations WHERE volunteer_id=? AND event_id=?",
                (volunteer["volunteer_id"], ev["event_id"]), one=True)
    if reg and reg["status"] in ACTIVE:
        return "rule_already"
    if reg and reg["status"] == "rejected":
        return "rule_rejected_before"
    clash = query("""SELECT e.title FROM registrations r JOIN events e USING (event_id)
                     WHERE r.volunteer_id = ? AND r.status IN ('pending','approved')
                       AND e.status = 'published' AND e.event_id <> ?
                       AND e.starts_at < ? AND e.ends_at > ? LIMIT 1""",
                  (volunteer["volunteer_id"], ev["event_id"], ev["ends_at"], ev["starts_at"]), one=True)
    if clash:
        return "rule_time_clash"
    taken = scalar("SELECT COUNT(*) FROM registrations WHERE event_id=? AND status IN ('approved','attended')",
                   (ev["event_id"],))
    if taken >= ev["max_volunteers"]:
        return "rule_full"
    return None


def apply(volunteer, event_id, motivation):
    """One transaction: lock -> re-check every rule (incl. free places) -> insert -> commit.
    BEGIN IMMEDIATE means a second volunteer waits until the first one finishes."""
    with transaction(immediate=True):
        ev = get_event(event_id)
        if not ev:
            raise RuleError("rule_not_open")
        problem = eligibility(volunteer, ev)
        if problem:
            raise RuleError(problem)
        status = "pending" if ev["requires_approval"] else "approved"
        decided = None if ev["requires_approval"] else now_str()
        existing = query("SELECT registration_id FROM registrations WHERE volunteer_id=? AND event_id=?",
                         (volunteer["volunteer_id"], event_id), one=True)
        if existing:  # re-applying after own cancellation
            reg_id = existing["registration_id"]
            execute("""UPDATE registrations SET status=?, motivation=?, applied_at=?, decided_at=?,
                       decided_by=NULL, decision_note=NULL WHERE registration_id=?""",
                    (status, motivation or None, now_str(), decided, reg_id))
        else:
            reg_id = execute("""INSERT INTO registrations (volunteer_id, event_id, status, motivation, decided_at)
                                VALUES (?,?,?,?,?)""",
                             (volunteer["volunteer_id"], event_id, status, motivation or None, decided))
        coord_user = scalar("SELECT user_id FROM coordinators WHERE coordinator_id=?", (ev["coordinator_id"],))
        notify(coord_user, "n_coord_new_application" if status == "pending" else "n_coord_new_participant",
               url_for("org.event_manage", event_id=event_id),
               name=volunteer["full_name"], event=ev["title"])
        notify(volunteer["user_id"], "n_applied" if status == "pending" else "n_approved",
               url_for("public.event_detail", event_id=event_id), event=ev["title"])
    return status


def cancel_by_volunteer(volunteer, registration_id):
    with transaction():
        reg = query("""SELECT r.*, e.title, e.starts_at, e.coordinator_id FROM registrations r
                       JOIN events e USING (event_id) WHERE r.registration_id=? AND r.volunteer_id=?""",
                    (registration_id, volunteer["volunteer_id"]), one=True)
        if not reg:
            raise RuleError("rule_not_found")
        if reg["status"] not in ACTIVE:
            raise RuleError("rule_cannot_cancel")
        if reg["starts_at"] <= now_str():
            raise RuleError("rule_started")
        execute("UPDATE registrations SET status='cancelled', decided_at=? WHERE registration_id=?",
                (now_str(), registration_id))
        if reg["status"] == "approved":
            coord_user = scalar("SELECT user_id FROM coordinators WHERE coordinator_id=?", (reg["coordinator_id"],))
            notify(coord_user, "n_coord_cancelled", url_for("org.event_manage", event_id=reg["event_id"]),
                   name=volunteer["full_name"], event=reg["title"])


def decide(coordinator, registration_id, approve, note=None):
    with transaction(immediate=True):
        reg = query("""SELECT r.*, e.title, e.max_volunteers, e.org_id, e.starts_at, e.status AS ev_status,
                              v.user_id AS vol_user
                       FROM registrations r JOIN events e USING (event_id)
                       JOIN volunteers v USING (volunteer_id) WHERE r.registration_id=?""",
                    (registration_id,), one=True)
        if not reg or reg["org_id"] != coordinator["org_id"]:
            raise RuleError("rule_not_found")
        if reg["status"] != "pending" or reg["ev_status"] != "published":
            raise RuleError("rule_not_pending")
        if reg["starts_at"] <= now_str():
            raise RuleError("rule_started")
        if approve:
            taken = scalar("SELECT COUNT(*) FROM registrations WHERE event_id=? AND status IN ('approved','attended')",
                           (reg["event_id"],))
            if taken >= reg["max_volunteers"]:
                raise RuleError("rule_full")
        new_status = "approved" if approve else "rejected"
        execute("""UPDATE registrations SET status=?, decided_at=?, decided_by=?, decision_note=?
                   WHERE registration_id=?""",
                (new_status, now_str(), coordinator["coordinator_id"], note or None, registration_id))
        audit("registration_" + new_status, "registrations", registration_id, "pending", new_status)
        notify(reg["vol_user"], "n_approved" if approve else "n_rejected",
               url_for("volunteer.applications"), event=reg["title"])


def mark_attendance(coordinator, registration_id, attended, hours=None):
    """Confirm hours (attended) or mark no-show. Every change of hours goes to the audit log."""
    with transaction():
        reg = query("""SELECT r.*, e.title, e.org_id, e.starts_at, e.ends_at, e.status AS ev_status,
                              v.user_id AS vol_user
                       FROM registrations r JOIN events e USING (event_id)
                       JOIN volunteers v USING (volunteer_id) WHERE r.registration_id=?""",
                    (registration_id,), one=True)
        if not reg or reg["org_id"] != coordinator["org_id"]:
            raise RuleError("rule_not_found")
        if reg["status"] not in ("approved", "attended", "no_show"):
            raise RuleError("rule_not_participant")
        if reg["ev_status"] == "cancelled":
            raise RuleError("rule_not_open")
        if reg["starts_at"] > now_str():
            raise RuleError("rule_not_started")
        if attended:
            limit = duration_hours(reg["starts_at"], reg["ends_at"])
            if hours is None or hours <= 0 or hours > min(24, limit):
                raise RuleError("rule_hours_range", max=limit)
            execute("""UPDATE registrations SET status='attended', hours_confirmed=?, confirmed_by=?,
                       confirmed_at=? WHERE registration_id=?""",
                    (hours, coordinator["coordinator_id"], now_str(), registration_id))
            if reg["hours_confirmed"] != hours:
                audit("hours_confirmed" if reg["hours_confirmed"] is None else "hours_changed",
                      "registrations", registration_id, reg["hours_confirmed"], hours)
                notify(reg["vol_user"], "n_hours_confirmed", url_for("volunteer.dashboard"),
                       event=reg["title"], hours=f"{hours:g}")
        else:
            execute("""UPDATE registrations SET status='no_show', hours_confirmed=NULL, confirmed_by=?,
                       confirmed_at=? WHERE registration_id=?""",
                    (coordinator["coordinator_id"], now_str(), registration_id))
            audit("marked_no_show", "registrations", registration_id, reg["hours_confirmed"], None)


def complete_event(coordinator, event_id):
    with transaction():
        ev = get_event(event_id)
        if not ev or ev["org_id"] != coordinator["org_id"]:
            raise RuleError("rule_not_found")
        if ev["status"] != "published" or ev["ends_at"] > now_str():
            raise RuleError("rule_not_finished")
        if scalar("SELECT COUNT(*) FROM registrations WHERE event_id=? AND status='approved'", (event_id,)):
            raise RuleError("rule_unmarked")
        for r in query("""SELECT r.registration_id, v.user_id FROM registrations r
                          JOIN volunteers v USING (volunteer_id) WHERE event_id=? AND status='pending'""",
                       (event_id,)):
            execute("UPDATE registrations SET status='rejected', decided_at=? WHERE registration_id=?",
                    (now_str(), r["registration_id"]))
        execute("UPDATE events SET status='completed', updated_at=? WHERE event_id=?", (now_str(), event_id))
        audit("event_completed", "events", event_id, "published", "completed")


def cancel_event(user_id_for_audit, event_id, reason):
    with transaction():
        ev = get_event(event_id)
        if not ev or ev["status"] not in ("published", "draft"):
            raise RuleError("rule_cannot_cancel")
        if ev["starts_at"] <= now_str() and ev["status"] == "published":
            raise RuleError("rule_started")
        execute("UPDATE events SET status='cancelled', cancel_reason=?, updated_at=? WHERE event_id=?",
                (reason, now_str(), event_id))
        for r in query("""SELECT v.user_id FROM registrations r JOIN volunteers v USING (volunteer_id)
                          WHERE r.event_id=? AND r.status IN ('pending','approved')""", (event_id,)):
            notify(r["user_id"], "n_event_cancelled", url_for("public.event_detail", event_id=event_id),
                   event=ev["title"], reason=reason)
        audit("event_cancelled", "events", event_id, ev["status"], "cancelled")


def new_certificate_code():
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(10))
        if not scalar("SELECT 1 FROM certificates WHERE code=?", (code,)):
            return code


def issue_certificate(volunteer, registration_id):
    reg = query("SELECT * FROM registrations WHERE registration_id=? AND volunteer_id=?",
                (registration_id, volunteer["volunteer_id"]), one=True)
    if not reg or reg["status"] != "attended":
        raise RuleError("rule_cert_attended")
    existing = scalar("SELECT code FROM certificates WHERE registration_id=?", (registration_id,))
    if existing:
        return existing
    code = new_certificate_code()
    execute("INSERT INTO certificates (registration_id, code) VALUES (?,?)", (registration_id, code))
    return code


def volunteer_stats(volunteer_id):
    row = query("""SELECT COALESCE(SUM(hours_confirmed),0) AS hours,
                          SUM(status='attended') AS attended,
                          SUM(status IN ('pending','approved')) AS active,
                          SUM(status='no_show') AS no_show
                   FROM registrations WHERE volunteer_id=?""", (volunteer_id,), one=True)
    hours = row["hours"] or 0
    nxt = next((m for m in MILESTONES if m > hours), None)
    prev = max([0] + [m for m in MILESTONES if m <= hours])
    progress = 100 if nxt is None else int((hours - prev) / (nxt - prev) * 100)
    return dict(hours=hours, attended=row["attended"] or 0, active=row["active"] or 0,
                no_show=row["no_show"] or 0, next_milestone=nxt, progress=progress,
                badges=[m for m in MILESTONES if m <= hours])


def org_stats(org_id):
    row = query("""SELECT COUNT(DISTINCT e.event_id) AS events,
                          SUM(e.status='completed') AS completed_rows,
                          COUNT(DISTINCT CASE WHEN r.status='attended' THEN r.volunteer_id END) AS volunteers,
                          COALESCE(SUM(CASE WHEN r.status='attended' THEN r.hours_confirmed END),0) AS hours,
                          SUM(r.status='attended') AS attended, SUM(r.status='no_show') AS no_show
                   FROM events e LEFT JOIN registrations r ON r.event_id = e.event_id
                   WHERE e.org_id=? AND e.status <> 'draft'""", (org_id,), one=True)
    completed = scalar("SELECT COUNT(*) FROM events WHERE org_id=? AND status='completed'", (org_id,))
    rating = query("""SELECT ROUND(AVG(f.rating),1) AS avg, COUNT(*) AS n FROM feedback f
                      JOIN registrations r USING (registration_id) JOIN events e USING (event_id)
                      WHERE e.org_id=? AND f.is_hidden=0""", (org_id,), one=True)
    att, ns = row["attended"] or 0, row["no_show"] or 0
    return dict(events=row["events"] or 0, completed=completed, volunteers=row["volunteers"] or 0,
                hours=row["hours"] or 0, attendance=round(att * 100 / (att + ns)) if att + ns else None,
                rating=rating["avg"], reviews=rating["n"])


def is_past(value):
    d = parse_dt(value)
    return d is not None and d <= datetime.now()
