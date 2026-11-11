import secrets
import string
from datetime import datetime

from flask import url_for

from .core import age_on, audit, duration_hours, notify, now_str, parse_dt
from .db import execute, query, scalar, transaction

ACTIVE = ("pending", "approved")
MILESTONES = (10, 20, 50, 100, 200)
NO_SHOW_ALERT = 3
CERT_MILESTONES = (20, 50, 100)
LEAD_MIN_HOURS, LEAD_MIN_RATE, LEAD_MIN_EVENTS = 30, 90, 5

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

PUBLIC_WHERE = "e.status IN ('published','completed') AND o.status = 'verified'"


def get_event(event_id):
    return query(EVENT_SELECT + " WHERE e.event_id = ?", (event_id,), one=True)


class RuleError(Exception):

    def __init__(self, key, **params):
        super().__init__(key)
        self.key = key
        self.params = params


def consent_status(volunteer_id):
    row = query("SELECT status FROM consents WHERE volunteer_id=? ORDER BY consent_id DESC LIMIT 1",
                (volunteer_id,), one=True)
    return row["status"] if row else None


def eligibility(volunteer, ev, from_waitlist=False):
    now = now_str()
    if ev["status"] != "published" or ev["org_status"] != "verified":
        return "rule_not_open"
    if ev["starts_at"] <= now:
        return "rule_started"
    if ev["registration_deadline"] < now and not from_waitlist:
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
    if from_waitlist:
        return None
    taken = scalar("SELECT COUNT(*) FROM registrations WHERE event_id=? AND status IN ('approved','attended')",
                   (ev["event_id"],))
    if taken >= ev["max_volunteers"]:
        return "rule_full"
    if scalar("SELECT 1 FROM waitlist WHERE event_id=? AND volunteer_id<>?", (ev["event_id"], volunteer["volunteer_id"])):
        return "rule_full"
    return None


def event_shifts(event_id):
    return query("SELECT * FROM event_shifts WHERE event_id=? ORDER BY position, starts_at", (event_id,))


def parse_shift_choice(event_id, value):
    value = (value or "").strip()
    if value == "all":
        return None, 1
    if value.isdigit() and scalar("SELECT 1 FROM event_shifts WHERE shift_id=? AND event_id=?", (int(value), event_id)):
        return int(value), 0
    return None, 0


def _register(volunteer, ev, motivation, pref=(None, 0)):
    status = "pending" if ev["requires_approval"] else "approved"
    decided = None if ev["requires_approval"] else now_str()
    existing = query("SELECT registration_id FROM registrations WHERE volunteer_id=? AND event_id=?",
                     (volunteer["volunteer_id"], ev["event_id"]), one=True)
    if existing:
        reg_id = existing["registration_id"]
        execute("""UPDATE registrations SET status=?, motivation=?, applied_at=?, decided_at=?,
                   decided_by=NULL, decision_note=NULL, is_team_lead=0, preferred_shift_id=?, prefers_all_shifts=?,
                   shift_id=NULL, all_shifts=0 WHERE registration_id=?""",
                (status, motivation or None, now_str(), decided, pref[0], pref[1], reg_id))
    else:
        reg_id = execute("""INSERT INTO registrations (volunteer_id, event_id, status, motivation, decided_at,
                            preferred_shift_id, prefers_all_shifts) VALUES (?,?,?,?,?,?,?)""",
                         (volunteer["volunteer_id"], ev["event_id"], status, motivation or None, decided,
                          pref[0], pref[1]))
    return reg_id, status


def apply(volunteer, event_id, motivation, shift_choice=None):
    with transaction(immediate=True):
        ev = get_event(event_id)
        if not ev:
            raise RuleError("rule_not_open")
        problem = eligibility(volunteer, ev)
        if problem:
            raise RuleError(problem)
        _reg_id, status = _register(volunteer, ev, motivation, parse_shift_choice(event_id, shift_choice))
        coord_user = scalar("SELECT user_id FROM coordinators WHERE coordinator_id=?", (ev["coordinator_id"],))
        notify(coord_user, "n_coord_new_application" if status == "pending" else "n_coord_new_participant",
               url_for("org.event_manage", event_id=event_id),
               name=volunteer["full_name"], event=ev["title"])
        notify(volunteer["user_id"], "n_applied" if status == "pending" else "n_approved",
               url_for("public.event_detail", event_id=event_id), event=ev["title"])
    return status


def waitlist_position(volunteer_id, event_id):
    row = query("SELECT waitlist_id, joined_at FROM waitlist WHERE volunteer_id=? AND event_id=?",
                (volunteer_id, event_id), one=True)
    if not row:
        return None
    return scalar("""SELECT COUNT(*) FROM waitlist WHERE event_id=?
                     AND (joined_at < ? OR (joined_at = ? AND waitlist_id <= ?))""",
                  (event_id, row["joined_at"], row["joined_at"], row["waitlist_id"]))


def join_waitlist(volunteer, event_id, motivation):
    with transaction(immediate=True):
        ev = get_event(event_id)
        if not ev:
            raise RuleError("rule_not_open")
        if scalar("SELECT 1 FROM waitlist WHERE volunteer_id=? AND event_id=?", (volunteer["volunteer_id"], event_id)):
            raise RuleError("rule_waitlist_already")
        problem = eligibility(volunteer, ev)
        if problem != "rule_full":
            raise RuleError(problem or "rule_waitlist_places_free")
        execute("INSERT INTO waitlist (volunteer_id, event_id, motivation) VALUES (?,?,?)",
                (volunteer["volunteer_id"], event_id, motivation or None))
        return waitlist_position(volunteer["volunteer_id"], event_id)


def leave_waitlist(volunteer, event_id):
    with transaction():
        if not scalar("SELECT 1 FROM waitlist WHERE volunteer_id=? AND event_id=?", (volunteer["volunteer_id"], event_id)):
            raise RuleError("rule_not_found")
        execute("DELETE FROM waitlist WHERE volunteer_id=? AND event_id=?", (volunteer["volunteer_id"], event_id))


def promote_waitlist(event_id):
    promoted = 0
    while True:
        ev = get_event(event_id)
        if not ev or ev["status"] != "published" or ev["starts_at"] <= now_str():
            return promoted
        held = ev["taken"] + (ev["pending"] if ev["requires_approval"] else 0)
        if held >= ev["max_volunteers"]:
            return promoted
        first = query("""SELECT w.waitlist_id, w.motivation, v.* FROM waitlist w JOIN volunteers v USING (volunteer_id)
                         WHERE w.event_id=? ORDER BY w.joined_at, w.waitlist_id LIMIT 1""", (event_id,), one=True)
        if not first:
            return promoted
        execute("DELETE FROM waitlist WHERE waitlist_id=?", (first["waitlist_id"],))
        link = url_for("public.event_detail", event_id=event_id)
        if eligibility(first, ev, from_waitlist=True):
            notify(first["user_id"], "n_waitlist_dropped", link, event=ev["title"])
            continue
        reg_id, status = _register(first, ev, first["motivation"])
        audit("waitlist_promoted", "registrations", reg_id, "waitlist", status)
        notify(first["user_id"], "n_waitlist_promoted" if status == "approved" else "n_waitlist_promoted_pending",
               link, event=ev["title"])
        coord_user = scalar("SELECT user_id FROM coordinators WHERE coordinator_id=?", (ev["coordinator_id"],))
        notify(coord_user, "n_coord_waitlist_promoted", url_for("org.event_manage", event_id=event_id),
               name=first["full_name"], event=ev["title"])
        promoted += 1


def cancel_by_volunteer(volunteer, registration_id):
    with transaction(immediate=True):
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
        promote_waitlist(reg["event_id"])


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
        if not approve:
            promote_waitlist(reg["event_id"])


def mark_attendance(coordinator, registration_id, attended, hours=None):
    with transaction():
        reg = query("""SELECT r.*, e.title, e.org_id, e.starts_at, e.ends_at, e.status AS ev_status,
                              v.user_id AS vol_user, sh.starts_at AS shift_start, sh.ends_at AS shift_end
                       FROM registrations r JOIN events e USING (event_id)
                       JOIN volunteers v USING (volunteer_id)
                       LEFT JOIN event_shifts sh ON sh.shift_id = r.shift_id AND r.all_shifts = 0
                       WHERE r.registration_id=?""",
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
            limit = duration_hours(reg["shift_start"] or reg["starts_at"], reg["shift_end"] or reg["ends_at"])
            if hours is None or hours <= 0 or hours > min(24, limit):
                raise RuleError("rule_hours_range", max=limit)
            before = total_hours(reg["volunteer_id"])
            execute("""UPDATE registrations SET status='attended', hours_confirmed=?, confirmed_by=?,
                       confirmed_at=? WHERE registration_id=?""",
                    (hours, coordinator["coordinator_id"], now_str(), registration_id))
            after = total_hours(reg["volunteer_id"])
            for m in CERT_MILESTONES:
                if before < m <= after:
                    notify(reg["vol_user"], "n_milestone_reached", url_for("volunteer.dashboard"), n=m)
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
        execute("DELETE FROM waitlist WHERE event_id=?", (event_id,))
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
                          WHERE r.event_id=? AND r.status IN ('pending','approved')
                          UNION SELECT v.user_id FROM waitlist w JOIN volunteers v USING (volunteer_id)
                          WHERE w.event_id=?""", (event_id, event_id)):
            notify(r["user_id"], "n_event_cancelled", url_for("public.event_detail", event_id=event_id),
                   event=ev["title"], reason=reason)
        execute("DELETE FROM waitlist WHERE event_id=?", (event_id,))
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


def total_hours(volunteer_id):
    return scalar("SELECT COALESCE(SUM(hours_confirmed), 0) FROM registrations WHERE volunteer_id=? AND status='attended'",
                  (volunteer_id,)) or 0


def milestone_certificates(volunteer_id):
    hours = total_hours(volunteer_id)
    issued = {r["milestone_hours"]: r["code"] for r in query(
        "SELECT milestone_hours, code FROM certificates WHERE type='milestone' AND volunteer_id=?", (volunteer_id,))}
    return [dict(hours=m, reached=hours >= m, code=issued.get(m), left=max(0, m - hours)) for m in CERT_MILESTONES]


def issue_milestone_certificate(volunteer, milestone):
    if milestone not in CERT_MILESTONES:
        raise RuleError("rule_not_found")
    with transaction(immediate=True):
        existing = scalar("SELECT code FROM certificates WHERE type='milestone' AND volunteer_id=? AND milestone_hours=?",
                          (volunteer["volunteer_id"], milestone))
        if existing:
            return existing
        if total_hours(volunteer["volunteer_id"]) < milestone:
            raise RuleError("rule_milestone_not_reached", n=milestone)
        code = new_certificate_code()
        execute("INSERT INTO certificates (type, volunteer_id, milestone_hours, code) VALUES ('milestone',?,?,?)",
                (volunteer["volunteer_id"], milestone, code))
        audit("milestone_certificate", "certificates", None, None, f"{milestone} h")
    return code


def milestone_events(volunteer_id, until):
    return query("""SELECT r.hours_confirmed, e.title, e.starts_at, o.name AS org_name,
                           c.name_en AS city_name_en, c.name_ru AS city_name_ru, c.name_kk AS city_name_kk
                    FROM registrations r JOIN events e USING (event_id) JOIN organizations o ON o.org_id=e.org_id
                    JOIN cities c ON c.city_id=e.city_id
                    WHERE r.volunteer_id=? AND r.status='attended' AND e.starts_at <= ?
                    ORDER BY e.starts_at""", (volunteer_id, until))


def subscriptions(volunteer_id):
    rows = query("SELECT city_id, direction_id FROM subscriptions WHERE volunteer_id=?", (volunteer_id,))
    return ({r["city_id"] for r in rows if r["city_id"]}, {r["direction_id"] for r in rows if r["direction_id"]})


def save_subscriptions(volunteer_id, city_ids, direction_ids):
    with transaction():
        execute("DELETE FROM subscriptions WHERE volunteer_id=?", (volunteer_id,))
        for cid in sorted(set(city_ids)):
            execute("INSERT INTO subscriptions (volunteer_id, city_id) VALUES (?,?)", (volunteer_id, cid))
        for did in sorted(set(direction_ids)):
            execute("INSERT INTO subscriptions (volunteer_id, direction_id) VALUES (?,?)", (volunteer_id, did))


SUBSCRIBED_TO = """EXISTS (SELECT 1 FROM subscriptions s WHERE s.volunteer_id = {v})
    AND (NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.volunteer_id = {v} AND s.city_id IS NOT NULL)
         OR EXISTS (SELECT 1 FROM subscriptions s WHERE s.volunteer_id = {v} AND s.city_id = {e}.city_id))
    AND (NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.volunteer_id = {v} AND s.direction_id IS NOT NULL)
         OR EXISTS (SELECT 1 FROM subscriptions s WHERE s.volunteer_id = {v} AND s.direction_id = {e}.direction_id))"""


def notify_subscribers(event_id):
    ev = get_event(event_id)
    if not ev or ev["status"] != "published" or ev["org_status"] != "verified":
        return 0
    start = parse_dt(ev["starts_at"])
    rows = query("""SELECT v.volunteer_id, v.user_id, v.birth_date FROM volunteers v JOIN users u ON u.user_id = v.user_id
                    JOIN events e ON e.event_id = ?
                    WHERE u.is_active = 1 AND """ + SUBSCRIBED_TO.format(v="v.volunteer_id", e="e") + """
                    AND NOT EXISTS (SELECT 1 FROM registrations r WHERE r.event_id = e.event_id AND r.volunteer_id = v.volunteer_id)""",
                 (event_id,))
    sent = 0
    for r in rows:
        age = age_on(r["birth_date"], start)
        if age is not None and age < ev["min_age"]:
            continue
        notify(r["user_id"], "n_new_for_you", url_for("public.event_detail", event_id=event_id),
               event=ev["title"], date=ev["starts_at"][:10])
        sent += 1
    return sent


def new_for_you(volunteer, limit=6):
    return query(EVENT_SELECT + f""" WHERE {PUBLIC_WHERE} AND e.status='published' AND e.registration_deadline >= ?
        AND e.min_age <= ? AND {SUBSCRIBED_TO.format(v="?", e="e")}
        AND NOT EXISTS (SELECT 1 FROM registrations r WHERE r.event_id=e.event_id AND r.volunteer_id=?)
        ORDER BY e.created_at DESC, e.starts_at LIMIT ?""",
                 (now_str(), age_on(volunteer["birth_date"]) or 0) + (volunteer["volunteer_id"],) * 5
                 + (volunteer["volunteer_id"], limit))


def reliability(volunteer_ids):
    ids = sorted({int(v) for v in volunteer_ids})
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    result = {r["volunteer_id"]: dict(attended=r["attended"], no_show=r["no_show"], rate=r["attendance_rate"], streak=0)
              for r in query(f"SELECT * FROM volunteer_reliability WHERE volunteer_id IN ({marks})", ids)}
    history = query(f"""SELECT r.volunteer_id, r.status FROM registrations r JOIN events e USING (event_id)
                        WHERE r.volunteer_id IN ({marks}) AND r.status IN ('attended','no_show')
                        ORDER BY r.volunteer_id, e.starts_at DESC""", ids)
    closed = set()
    for row in history:
        vid = row["volunteer_id"]
        if vid in closed:
            continue
        if row["status"] == "no_show":
            result[vid]["streak"] += 1
        else:
            closed.add(vid)
    for item in result.values():
        total = item["attended"] + item["no_show"]
        item["total"] = total
        item["alert"] = item["streak"] >= NO_SHOW_ALERT
        if total == 0:
            item["level"] = "new"
        elif item["alert"] or item["rate"] < 60:
            item["level"] = "low"
        elif item["rate"] < 85:
            item["level"] = "mid"
        else:
            item["level"] = "good"
    return result


def shift_load(event_id):
    shifts = event_shifts(event_id)
    regs = query("""SELECT shift_id, all_shifts FROM registrations
                    WHERE event_id=? AND status IN ('approved','attended')""", (event_id,))
    load = {s["shift_id"]: 0 for s in shifts}
    unassigned = 0
    for r in regs:
        if r["all_shifts"]:
            for k in load:
                load[k] += 1
        elif r["shift_id"] in load:
            load[r["shift_id"]] += 1
        else:
            unassigned += 1
    return shifts, load, unassigned


def propose_shifts(event_id):
    shifts, load, _u = shift_load(event_id)
    if not shifts:
        return {}
    need = {s["shift_id"]: s["max_volunteers"] for s in shifts}
    order = [s["shift_id"] for s in shifts]
    people = query("""SELECT registration_id, preferred_shift_id, prefers_all_shifts FROM registrations
                      WHERE event_id=? AND status IN ('approved','attended') AND shift_id IS NULL AND all_shifts=0
                      ORDER BY applied_at, registration_id""", (event_id,))
    plan, rest = {}, []
    for p in people:
        if p["prefers_all_shifts"] and all(load[k] < need[k] for k in order):
            plan[p["registration_id"]] = "all"
            for k in order:
                load[k] += 1
        elif p["preferred_shift_id"] in need and load[p["preferred_shift_id"]] < need[p["preferred_shift_id"]]:
            plan[p["registration_id"]] = str(p["preferred_shift_id"])
            load[p["preferred_shift_id"]] += 1
        else:
            rest.append(p)
    for p in rest:
        free = [(need[k] - load[k], -i, k) for i, k in enumerate(order) if load[k] < need[k]]
        if not free:
            plan[p["registration_id"]] = ""
            continue
        k = max(free)[2]
        plan[p["registration_id"]] = str(k)
        load[k] += 1
    return plan


def save_shifts(coordinator, event_id, choices):
    changed = 0
    with transaction(immediate=True):
        ev = get_event(event_id)
        if not ev or ev["org_id"] != coordinator["org_id"]:
            raise RuleError("rule_not_found")
        shifts = {s["shift_id"]: s for s in event_shifts(event_id)}
        if not shifts:
            raise RuleError("rule_no_shifts")
        regs = query("""SELECT r.*, v.user_id AS vol_user FROM registrations r JOIN volunteers v USING (volunteer_id)
                        WHERE r.event_id=? AND r.status IN ('approved','attended','no_show')""", (event_id,))
        for r in regs:
            if r["registration_id"] not in choices:
                continue
            shift_id, all_flag = parse_shift_choice(event_id, choices[r["registration_id"]])
            if (shift_id, all_flag) == (r["shift_id"], r["all_shifts"]):
                continue
            execute("UPDATE registrations SET shift_id=?, all_shifts=? WHERE registration_id=?",
                    (shift_id, all_flag, r["registration_id"]))
            label = "all" if all_flag else (str(shift_id) if shift_id else "")
            audit("shift_assigned", "registrations", r["registration_id"],
                  "all" if r["all_shifts"] else r["shift_id"], label or None)
            changed += 1
            if r["status"] == "approved" and (shift_id or all_flag):
                if all_flag:
                    notify(r["vol_user"], "n_shift_all", url_for("public.event_detail", event_id=event_id),
                           event=ev["title"], start=ev["starts_at"][11:16], end=ev["ends_at"][11:16])
                else:
                    sh = shifts[shift_id]
                    notify(r["vol_user"], "n_shift_assigned", url_for("public.event_detail", event_id=event_id),
                           event=ev["title"], shift=sh["title"], start=sh["starts_at"][11:16], end=sh["ends_at"][11:16])
    return changed


def lead_candidates(volunteer_ids):
    ids = sorted({int(v) for v in volunteer_ids})
    if not ids:
        return set()
    marks = ",".join("?" * len(ids))
    hours = {r["volunteer_id"]: r["h"] for r in query(f"""SELECT volunteer_id, SUM(hours_confirmed) AS h FROM registrations
        WHERE status='attended' AND volunteer_id IN ({marks}) GROUP BY volunteer_id""", ids)}
    return {vid for vid, rel in reliability(ids).items()
            if (hours.get(vid) or 0) >= LEAD_MIN_HOURS and rel["total"] >= LEAD_MIN_EVENTS
            and (rel["rate"] or 0) >= LEAD_MIN_RATE and not rel["alert"]}


def set_team_lead(coordinator, registration_id, on):
    with transaction():
        reg = query("""SELECT r.*, e.title, e.org_id, e.ends_at, e.status AS ev_status, v.user_id AS vol_user
                       FROM registrations r JOIN events e USING (event_id) JOIN volunteers v USING (volunteer_id)
                       WHERE r.registration_id=?""", (registration_id,), one=True)
        if not reg or reg["org_id"] != coordinator["org_id"]:
            raise RuleError("rule_not_found")
        if reg["status"] != "approved" or reg["ev_status"] != "published" or reg["ends_at"] <= now_str():
            raise RuleError("rule_team_lead_status")
        if bool(reg["is_team_lead"]) == bool(on):
            return
        execute("UPDATE registrations SET is_team_lead=? WHERE registration_id=?", (1 if on else 0, registration_id))
        audit("team_lead_assigned" if on else "team_lead_removed", "registrations", registration_id,
              reg["is_team_lead"], 1 if on else 0)
        notify(reg["vol_user"], "n_team_lead_assigned" if on else "n_team_lead_removed",
               url_for("public.event_detail", event_id=reg["event_id"]), event=reg["title"])


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
