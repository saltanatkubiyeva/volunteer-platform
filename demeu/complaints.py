from flask import url_for

from . import services as S
from .core import audit, notify, now_str
from .db import execute, query, scalar, transaction

REASONS = ("fake", "unsafe", "inappropriate", "fraud", "other")
ACTIONS = ("none", "event_cancelled", "org_suspended", "account_blocked")


def target(event_id=None, org_id=None):
    if event_id:
        ev = query("""SELECT e.event_id, e.title AS name, e.org_id, e.coordinator_id, e.status, o.name AS org_name
                      FROM events e JOIN organizations o USING (org_id) WHERE e.event_id=?""", (event_id,), one=True)
        return dict(ev, kind="event") if ev else None
    org = query("SELECT org_id, name, status FROM organizations WHERE org_id=?", (org_id,), one=True)
    return dict(org, kind="organization") if org else None


def can_report(user, t):
    if not user or not t or user["role"] == "admin":
        return False
    if user["role"] == "coordinator":
        own_org = scalar("SELECT org_id FROM coordinators WHERE user_id=?", (user["user_id"],))
        if own_org == t["org_id"]:
            return False
    return True


def submit(user, event_id, org_id, reason, details):
    t = target(event_id, org_id)
    if not can_report(user, t):
        raise S.RuleError("rule_cannot_report")
    if reason not in REASONS:
        raise S.RuleError("err_report_reason")
    if reason == "other" and len(details or "") < 10:
        raise S.RuleError("err_report_details")
    col = "event_id" if t["kind"] == "event" else "org_id"
    if scalar(f"SELECT 1 FROM complaints WHERE reporter_id=? AND {col}=? AND status='new'",
              (user["user_id"], t["event_id"] if t["kind"] == "event" else t["org_id"])):
        raise S.RuleError("rule_report_already")
    with transaction():
        cid = execute("""INSERT INTO complaints (reporter_id, event_id, org_id, reason, details) VALUES (?,?,?,?,?)""",
                      (user["user_id"], t.get("event_id") if t["kind"] == "event" else None,
                       t["org_id"] if t["kind"] == "organization" else None, reason, details or None))
        for (admin_id,) in query("SELECT user_id FROM users WHERE role='admin' AND is_active=1"):
            notify(admin_id, "n_admin_new_complaint", url_for("admin.complaints"), name=t["name"])
    return cid


def blockable_users(t):
    if t["kind"] == "event":
        return query("""SELECT u.user_id, u.email, c.full_name FROM coordinators c JOIN users u USING (user_id)
                        WHERE c.coordinator_id=?""", (t["coordinator_id"],))
    return query("""SELECT u.user_id, u.email, c.full_name FROM coordinators c JOIN users u USING (user_id)
                    WHERE c.org_id=? ORDER BY c.is_owner DESC""", (t["org_id"],))


def decide(admin, complaint_id, decision, action, note):
    c = query("SELECT * FROM complaints WHERE complaint_id=?", (complaint_id,), one=True)
    if not c or c["status"] != "new":
        raise S.RuleError("rule_not_found")
    if decision not in ("resolved", "dismissed"):
        raise S.RuleError("rule_not_found")
    if len(note or "") < 5:
        raise S.RuleError("err_comment_required")
    action = action if decision == "resolved" and action in ACTIONS else "none"
    t = target(c["event_id"], c["org_id"])
    link = url_for("public.event_detail", event_id=t["event_id"]) if t["kind"] == "event" \
        else url_for("public.organization_profile", org_id=t["org_id"])
    if action == "event_cancelled":
        if t["kind"] != "event":
            raise S.RuleError("rule_not_found")
        S.cancel_event(admin["user_id"], t["event_id"], note)
    with transaction():
        if action == "org_suspended":
            execute("UPDATE organizations SET status='suspended', status_comment=? WHERE org_id=?", (note, t["org_id"]))
            audit("org_suspended", "organizations", t["org_id"], t.get("status"), "suspended")
            for (uid,) in query("SELECT user_id FROM coordinators WHERE org_id=?", (t["org_id"],)):
                notify(uid, "n_org_suspended", url_for("org.dashboard"), reason=note)
        elif action == "account_blocked":
            for u in blockable_users(t)[:1]:
                execute("UPDATE users SET is_active=0 WHERE user_id=?", (u["user_id"],))
                audit("account_blocked", "users", u["user_id"], 1, 0)
        col, val = ("event_id", c["event_id"]) if c["event_id"] else ("org_id", c["org_id"])
        same = query(f"SELECT complaint_id, reporter_id FROM complaints WHERE {col}=? AND status='new'", (val,))
        for s in same:
            execute("""UPDATE complaints SET status=?, action=?, admin_note=?, handled_by=?, handled_at=?
                       WHERE complaint_id=?""", (decision, action, note, admin["user_id"], now_str(), s["complaint_id"]))
            notify(s["reporter_id"], "n_report_resolved" if decision == "resolved" and action != "none"
                   else "n_report_reviewed", link, name=t["name"])
        audit("complaint_" + decision, "complaints", complaint_id, "new", action)
    return len(same)
