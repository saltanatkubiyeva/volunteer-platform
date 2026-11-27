from flask import g, url_for

from . import services as S
from .core import audit, notify, now_str
from .db import execute, query, scalar, transaction

MAX_PARTNERS = 5
INVOLVED = "e.event_id IN (SELECT event_id FROM org_events WHERE org_id=?)"

ROW = """SELECT p.*, o.name, o.logo_path, o.status AS org_status, c.name_en AS city_name_en, c.name_ru AS city_name_ru,
    c.name_kk AS city_name_kk FROM event_partners p JOIN organizations o ON o.org_id = p.org_id
    JOIN cities c ON c.city_id = o.city_id"""


def role(org_id, ev):
    if not ev or not org_id:
        return None
    if ev["org_id"] == org_id:
        return "host"
    status = scalar("SELECT status FROM event_partners WHERE event_id=? AND org_id=?", (ev["event_id"], org_id))
    return {"accepted": "partner", "pending": "invited"}.get(status)


def can_manage(org_id, event_id):
    return bool(scalar("SELECT 1 FROM org_events WHERE event_id=? AND org_id=?", (event_id, org_id)))


def for_event(event_id):
    return query(ROW + " WHERE p.event_id=? ORDER BY p.status='accepted' DESC, p.invited_at", (event_id,))


def accepted_map():
    if "event_partners" not in g:
        out = {}
        for r in query(ROW + " WHERE p.status='accepted' AND o.deleted_at IS NULL ORDER BY p.responded_at"):
            out.setdefault(r["event_id"], []).append(r)
        g.event_partners = out
    return g.event_partners


def partners_of(event_id):
    return accepted_map().get(event_id, [])


def choices(org_id, city_id, event_id=None):
    return query("""SELECT o.org_id, o.name, o.logo_path, c.name_en AS city_name_en, c.name_ru AS city_name_ru,
        c.name_kk AS city_name_kk, p.status AS partner_status
        FROM organizations o JOIN cities c USING (city_id)
        LEFT JOIN event_partners p ON p.org_id = o.org_id AND p.event_id = ?
        WHERE o.status='verified' AND o.deleted_at IS NULL AND o.org_id<>?
        ORDER BY o.city_id<>?, o.name""", (event_id or 0, org_id, city_id))


def invite_many(coordinator, user, event_id, org_ids):
    sent = 0
    for oid in org_ids:
        try:
            invite(coordinator, user, event_id, oid)
            sent += 1
        except S.RuleError:
            pass
    return sent


def invitations(org_id):
    return query(S.EVENT_SELECT.replace("SELECT e.*,", "SELECT e.*, p.partner_id, p.invited_at,", 1)
                 + """ JOIN event_partners p ON p.event_id = e.event_id
                 WHERE p.org_id=? AND p.status='pending' AND e.deleted_at IS NULL AND e.status IN ('draft','published')
                   AND e.starts_at > ? ORDER BY e.starts_at""", (org_id, now_str()))


def invitations_count(org_id):
    return scalar("""SELECT COUNT(*) FROM event_partners p JOIN events e USING (event_id)
                     WHERE p.org_id=? AND p.status='pending' AND e.deleted_at IS NULL
                       AND e.status IN ('draft','published') AND e.starts_at > ?""", (org_id, now_str()))


def _open(ev):
    if not ev or ev["deleted_at"] or ev["status"] not in ("draft", "published") or ev["starts_at"] <= now_str():
        raise S.RuleError("rule_partner_closed")


def _team(org_id):
    return [r[0] for r in query("""SELECT c.user_id FROM coordinators c JOIN users u USING (user_id)
                                   WHERE c.org_id=? AND u.is_active=1 AND u.deleted_at IS NULL""", (org_id,))]


def invite(coordinator, user, event_id, org_id):
    with transaction(immediate=True):
        ev = S.get_event(event_id)
        if not ev or ev["org_id"] != coordinator["org_id"]:
            raise S.RuleError("rule_not_found")
        _open(ev)
        org = query("SELECT * FROM organizations WHERE org_id=?", (org_id,), one=True)
        if not org or org["status"] != "verified" or org["deleted_at"] or org_id == ev["org_id"]:
            raise S.RuleError("rule_partner_org")
        row = query("SELECT * FROM event_partners WHERE event_id=? AND org_id=?", (event_id, org_id), one=True)
        if row and row["status"] in ("pending", "accepted"):
            raise S.RuleError("rule_partner_exists")
        busy = scalar("SELECT COUNT(*) FROM event_partners WHERE event_id=? AND status IN ('pending','accepted')", (event_id,))
        if busy >= MAX_PARTNERS:
            raise S.RuleError("rule_partner_limit", n=MAX_PARTNERS)
        if row:
            execute("""UPDATE event_partners SET status='pending', invited_by=?, invited_at=?, responded_by=NULL,
                       responded_at=NULL WHERE partner_id=?""", (user["user_id"], now_str(), row["partner_id"]))
            pid = row["partner_id"]
        else:
            pid = execute("INSERT INTO event_partners (event_id, org_id, invited_by, invited_at) VALUES (?,?,?,?)",
                          (event_id, org_id, user["user_id"], now_str()))
        for uid in _team(org_id):
            notify(uid, "n_partner_invite", url_for("org.events", tab="invites"), org=ev["org_name"], event=ev["title"])
        audit("partner_invited", "event_partners", pid, None, f"event {event_id} → org {org_id}")
    return pid


def respond(coordinator, user, partner_id, accept):
    with transaction(immediate=True):
        p = query("SELECT * FROM event_partners WHERE partner_id=?", (partner_id,), one=True)
        if not p or p["org_id"] != coordinator["org_id"] or p["status"] != "pending":
            raise S.RuleError("rule_not_found")
        ev = S.get_event(p["event_id"])
        _open(ev)
        status = "accepted" if accept else "declined"
        execute("UPDATE event_partners SET status=?, responded_by=?, responded_at=? WHERE partner_id=?",
                (status, user["user_id"], now_str(), partner_id))
        name = scalar("SELECT name FROM organizations WHERE org_id=?", (p["org_id"],))
        for uid in _team(ev["org_id"]):
            notify(uid, "n_partner_" + status, url_for("org.event_manage", event_id=ev["event_id"], tab="partners"),
                   org=name, event=ev["title"])
        audit("partner_" + status, "event_partners", partner_id, "pending", status)
    return ev


def remove(coordinator, user, partner_id):
    with transaction(immediate=True):
        p = query("SELECT * FROM event_partners WHERE partner_id=?", (partner_id,), one=True)
        if not p:
            raise S.RuleError("rule_not_found")
        ev = S.get_event(p["event_id"])
        host = ev and ev["org_id"] == coordinator["org_id"]
        own = p["org_id"] == coordinator["org_id"] and p["status"] == "accepted"
        if not host and not own:
            raise S.RuleError("rule_not_found")
        if p["status"] == "accepted":
            _open(ev)
        execute("DELETE FROM event_partners WHERE partner_id=?", (partner_id,))
        name = scalar("SELECT name FROM organizations WHERE org_id=?", (p["org_id"],))
        if host and p["status"] == "accepted":
            for uid in _team(p["org_id"]):
                notify(uid, "n_partner_removed", url_for("org.events"), org=ev["org_name"], event=ev["title"])
        elif own:
            for uid in _team(ev["org_id"]):
                notify(uid, "n_partner_left", url_for("org.event_manage", event_id=ev["event_id"], tab="partners"),
                       org=name, event=ev["title"])
        audit("partner_left" if own and not host else "partner_removed", "event_partners", partner_id, p["status"], None)
    return ev, own and not host
