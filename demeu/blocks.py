from datetime import datetime, timedelta

from flask import url_for

from . import services as S
from .core import _, audit, notify, now_str
from .db import execute, query, scalar, transaction

DURATIONS = {"7": 7, "30": 30, "forever": None}
FMT = "%Y-%m-%d %H:%M"


def active_block(user_id):
    return query("""SELECT * FROM blocks WHERE user_id=? AND lifted_at IS NULL AND (ends_at IS NULL OR ends_at > ?)
                    ORDER BY block_id DESC LIMIT 1""", (user_id, now_str()), one=True)


def block_user(admin, user_id, duration, reason):
    user = query("SELECT * FROM users WHERE user_id=?", (user_id,), one=True)
    if not user or user["deleted_at"]:
        raise S.RuleError("err_block_user")
    if user["role"] == "admin" or user_id == admin["user_id"]:
        raise S.RuleError("rule_block_admin")
    if duration not in DURATIONS:
        raise S.RuleError("err_block_duration")
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise S.RuleError("err_block_reason")
    current = active_block(user_id)
    if current:
        raise S.RuleError("rule_block_exists")
    with transaction():
        return add_user_block(admin["user_id"], user, DURATIONS[duration], reason)


def add_user_block(admin_id, user, days, reason):
    now = datetime.now()
    ends = (now + timedelta(days=days)).strftime(FMT) if days else None
    bid = execute("INSERT INTO blocks (user_id, reason, starts_at, ends_at, blocked_by) VALUES (?,?,?,?,?)",
                  (user["user_id"], reason, now.strftime(FMT), ends, admin_id))
    execute("INSERT INTO outbox (user_id, to_email, subject, body) VALUES (?,?,?,?)",
            (user["user_id"], user["email"], _("mail_block_subject"),
             _("mail_block_body_until", d=ends, reason=reason) if ends else _("mail_block_body_forever", reason=reason)))
    audit("user_blocked", "users", user["user_id"], None, f"{days or 'forever'}: {reason}")
    return bid


def unblock(admin, block_id):
    b = query("SELECT * FROM blocks WHERE block_id=?", (block_id,), one=True)
    if not b or b["lifted_at"] or (b["ends_at"] and b["ends_at"] <= now_str()):
        raise S.RuleError("rule_not_found")
    with transaction():
        execute("UPDATE blocks SET lifted_at=?, lifted_by=? WHERE block_id=?", (now_str(), admin["user_id"], block_id))
        if b["user_id"]:
            notify(b["user_id"], "n_unblocked", url_for("auth.login"))
            audit("user_unblocked", "users", b["user_id"], b["reason"], None)
    return b


def suspend_org(admin_id, org_id, reason):
    execute("UPDATE blocks SET lifted_at=?, lifted_by=? WHERE org_id=? AND lifted_at IS NULL",
            (now_str(), admin_id, org_id))
    execute("INSERT INTO blocks (org_id, reason, starts_at, blocked_by) VALUES (?,?,?,?)",
            (org_id, reason, now_str(), admin_id))
    name = scalar("SELECT name FROM organizations WHERE org_id=?", (org_id,))
    for (uid,) in query("""SELECT DISTINCT v.user_id FROM registrations r JOIN volunteers v USING (volunteer_id)
                           JOIN events e USING (event_id) WHERE e.org_id=? AND e.status='published'
                           AND e.starts_at > ? AND r.status IN ('pending','approved')""", (org_id, now_str())):
        notify(uid, "n_org_paused_volunteer", url_for("volunteer.dashboard"), org=name)


def lift_org(admin_id, org_id):
    execute("UPDATE blocks SET lifted_at=?, lifted_by=? WHERE org_id=? AND lifted_at IS NULL",
            (now_str(), admin_id, org_id))


def state(b):
    if b["lifted_at"]:
        return "lifted"
    if b["ends_at"] and b["ends_at"] <= now_str():
        return "expired"
    return "active"


HISTORY_SQL = """SELECT b.*, u.email, u.role, COALESCE(v.full_name, c.full_name) AS person, o.name AS org_name,
    ab.email AS blocked_by_email, al.email AS lifted_by_email
    FROM blocks b LEFT JOIN users u ON u.user_id = b.user_id
    LEFT JOIN volunteers v ON v.user_id = b.user_id LEFT JOIN coordinators c ON c.user_id = b.user_id
    LEFT JOIN organizations o ON o.org_id = b.org_id
    LEFT JOIN users ab ON ab.user_id = b.blocked_by LEFT JOIN users al ON al.user_id = b.lifted_by"""


def rows(tab):
    now = now_str()
    if tab == "history":
        return query(HISTORY_SQL + " ORDER BY b.starts_at DESC LIMIT 200")
    if tab == "orgs":
        return query(HISTORY_SQL + " WHERE b.org_id IS NOT NULL AND b.lifted_at IS NULL ORDER BY b.starts_at DESC")
    return query(HISTORY_SQL + """ WHERE b.user_id IS NOT NULL AND b.lifted_at IS NULL
                 AND (b.ends_at IS NULL OR b.ends_at > ?) ORDER BY b.starts_at DESC""", (now,))


def counts():
    now = now_str()
    return dict(active=scalar("""SELECT COUNT(*) FROM blocks WHERE user_id IS NOT NULL AND lifted_at IS NULL
                                 AND (ends_at IS NULL OR ends_at > ?)""", (now,)),
                orgs=scalar("SELECT COUNT(*) FROM blocks WHERE org_id IS NOT NULL AND lifted_at IS NULL"),
                history=scalar("SELECT COUNT(*) FROM blocks"))
