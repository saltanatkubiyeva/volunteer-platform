import sqlite3
from datetime import datetime, timedelta

from . import services as S
from .core import audit, now_str
from .db import execute, query, scalar, transaction

KEEP_DAYS = 30
FMT = "%Y-%m-%d %H:%M"


def days_left(deleted_at):
    left = datetime.strptime(deleted_at[:16], FMT) + timedelta(days=KEEP_DAYS) - datetime.now()
    return max(0, left.days + (1 if left.seconds else 0))


def expires_on(deleted_at):
    return (datetime.strptime(deleted_at[:16], FMT) + timedelta(days=KEEP_DAYS)).strftime(FMT)


def can_delete_event(ev):
    if ev["deleted_at"]:
        return "rule_trash_already"
    if ev["status"] not in ("draft", "cancelled"):
        return "rule_trash_event_status"
    return None


def can_delete_org(org_id):
    org = query("SELECT * FROM organizations WHERE org_id=?", (org_id,), one=True)
    if not org:
        return "rule_not_found"
    if org["deleted_at"]:
        return "rule_trash_already"
    if org["status"] == "verified":
        return "rule_trash_org_verified"
    if scalar("""SELECT COUNT(*) FROM registrations r JOIN events e USING (event_id)
                 WHERE e.org_id=? AND r.status IN ('approved','attended')""", (org_id,)):
        return "rule_trash_org_people"
    return None


def delete_event(user, event_id):
    ev = query("SELECT * FROM events WHERE event_id=?", (event_id,), one=True)
    if not ev:
        raise S.RuleError("rule_not_found")
    problem = can_delete_event(ev)
    if problem:
        raise S.RuleError(problem)
    with transaction():
        execute("UPDATE events SET deleted_at=?, deleted_by=? WHERE event_id=?", (now_str(), user["user_id"], event_id))
        execute("DELETE FROM waitlist WHERE event_id=?", (event_id,))
        audit("trash_event", "events", event_id, ev["status"], "deleted")


def delete_org(user, org_id):
    problem = can_delete_org(org_id)
    if problem:
        raise S.RuleError(problem)
    with transaction():
        execute("UPDATE organizations SET deleted_at=?, deleted_by=? WHERE org_id=?", (now_str(), user["user_id"], org_id))
        audit("trash_org", "organizations", org_id, None, "deleted")


def restore(user, kind, item_id, org_id=None):
    table, pk = ("events", "event_id") if kind == "event" else ("organizations", "org_id")
    row = query(f"SELECT * FROM {table} WHERE {pk}=?", (item_id,), one=True)
    if not row or not row["deleted_at"] or (org_id and row["org_id"] != org_id):
        raise S.RuleError("rule_not_found")
    if kind == "event" and scalar("SELECT deleted_at FROM organizations WHERE org_id=?", (row["org_id"],)):
        raise S.RuleError("rule_trash_restore_org_first")
    with transaction():
        execute(f"UPDATE {table} SET deleted_at=NULL, deleted_by=NULL WHERE {pk}=?", (item_id,))
        audit("trash_restore", table, item_id, row["deleted_at"], "restored")
    return row


def _purge_event(event_id):
    execute("""DELETE FROM registrations WHERE event_id=? AND status IN ('pending','rejected','cancelled')""", (event_id,))
    execute("UPDATE events SET series_id=NULL WHERE series_id=? AND event_id<>?", (event_id, event_id))
    execute("DELETE FROM events WHERE event_id=?", (event_id,))


def _purge_org(org_id):
    for (eid,) in query("SELECT event_id FROM events WHERE org_id=?", (org_id,)):
        _purge_event(eid)
    users = [r["user_id"] for r in query("SELECT user_id FROM coordinators WHERE org_id=?", (org_id,))]
    execute("DELETE FROM coordinators WHERE org_id=?", (org_id,))
    for uid in users:
        execute("DELETE FROM users WHERE user_id=?", (uid,))
    execute("DELETE FROM organizations WHERE org_id=?", (org_id,))


def delete_forever(user, kind, item_id):
    table, pk = ("events", "event_id") if kind == "event" else ("organizations", "org_id")
    row = query(f"SELECT * FROM {table} WHERE {pk}=?", (item_id,), one=True)
    if not row or not row["deleted_at"]:
        raise S.RuleError("rule_not_found")
    try:
        with transaction():
            (_purge_event if kind == "event" else _purge_org)(item_id)
            audit("trash_purge", table, item_id, row["deleted_at"], "deleted forever")
    except sqlite3.IntegrityError:
        raise S.RuleError("rule_trash_purge_blocked")


def purge_expired():
    limit = (datetime.now() - timedelta(days=KEEP_DAYS)).strftime(FMT)
    done = 0
    for r in query("SELECT kind, item_id FROM trash_items WHERE deleted_at <= ? ORDER BY kind DESC", (limit,)):
        try:
            with transaction():
                (_purge_event if r["kind"] == "event" else _purge_org)(r["item_id"])
                audit("trash_auto_purge", "events" if r["kind"] == "event" else "organizations", r["item_id"])
            done += 1
        except sqlite3.IntegrityError:
            pass
    return done


def items(org_id=None):
    sql = """SELECT t.*, u.email AS deleted_by_email FROM trash_items t
             LEFT JOIN users u ON u.user_id = t.deleted_by"""
    if org_id:
        return query(sql + " WHERE t.kind='event' AND t.org_id=? ORDER BY t.deleted_at DESC", (org_id,))
    return query(sql + " ORDER BY t.deleted_at DESC")
