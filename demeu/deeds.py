import secrets
from datetime import date, datetime, timedelta

from flask import url_for

from . import services as S
from .core import _, audit, notify, now_str
from .db import execute, query, scalar, transaction
from .resets import token_hash

TAKE_DAYS = 7
WHEN_KINDS = ("on", "by", "any")


def _mail(req, subject_key, body_key, link=None, **params):
    execute("INSERT INTO outbox (user_id, to_email, subject, body, link) VALUES (?,?,?,?,?)",
            (req["user_id"], req["contact_email"], _(subject_key, title=req["title"]),
             _(body_key, title=req["title"], link=link or "", **params), link))


def status_link(token):
    return url_for("public.deed_status", token=token, _external=True)


def create(f, user=None):
    token = secrets.token_urlsafe(24)
    confirmed = user is not None
    with transaction():
        rid = execute("""INSERT INTO deed_requests (title, description, direction_id, city_id, area, when_kind, when_date,
            people_needed, contact_name, contact_email, contact_phone, user_id, token_hash, status, confirmed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (f["title"], f["description"], f["direction_id"], f["city_id"], f["area"], f["when_kind"],
                       f["when_date"] or None, f["people_needed"], f["contact_name"], f["contact_email"],
                       f["contact_phone"] or None, user["user_id"] if user else None, token_hash(token),
                       "pending" if confirmed else "unconfirmed", now_str() if confirmed else None))
        req = get(rid)
        if confirmed:
            _mail(req, "mail_deed_received_subject", "mail_deed_received_body", status_link(token))
            _notify_admins()
        else:
            _mail(req, "mail_deed_confirm_subject", "mail_deed_confirm_body",
                  url_for("public.deed_confirm", token=token, _external=True))
        audit("deed_created", "deed_requests", rid, None, req["status"])
    return rid, token


def _notify_admins():
    for (admin_id,) in query("SELECT user_id FROM users WHERE role='admin' AND is_active=1"):
        notify(admin_id, "n_admin_deed", url_for("admin.deeds"))


def get(request_id):
    return query("""SELECT d.*, c.name_en AS city_name_en, c.name_ru AS city_name_ru, c.name_kk AS city_name_kk,
        dr.slug AS dir_slug, dr.name_en AS dir_name_en, dr.name_ru AS dir_name_ru, dr.name_kk AS dir_name_kk,
        dr.icon AS dir_icon, dr.tone AS dir_tone, o.name AS org_name
        FROM deed_requests d JOIN cities c USING (city_id) JOIN directions dr USING (direction_id)
        LEFT JOIN organizations o ON o.org_id = d.taken_org_id WHERE d.request_id=?""", (request_id,), one=True)


def by_token(token):
    rid = scalar("SELECT request_id FROM deed_requests WHERE token_hash=?", (token_hash(token or ""),))
    return get(rid) if rid else None


def confirm(token):
    req = by_token(token)
    if not req:
        return None
    if req["status"] == "unconfirmed":
        with transaction():
            execute("UPDATE deed_requests SET status='pending', confirmed_at=? WHERE request_id=?",
                    (now_str(), req["request_id"]))
            _notify_admins()
            audit("deed_confirmed", "deed_requests", req["request_id"], "unconfirmed", "pending")
    return by_token(token)


def withdraw(token):
    req = by_token(token)
    if not req or req["status"] not in ("unconfirmed", "pending", "open"):
        raise S.RuleError("rule_deed_cannot_withdraw")
    execute("UPDATE deed_requests SET status='withdrawn', closed_at=? WHERE request_id=?", (now_str(), req["request_id"]))
    audit("deed_withdrawn", "deed_requests", req["request_id"], req["status"], "withdrawn")


def moderate(admin, request_id, action, reason=None):
    req = get(request_id)
    if not req or req["status"] != "pending" or action not in ("approve", "reject"):
        raise S.RuleError("rule_not_found")
    if action == "reject" and len((reason or "").strip()) < 5:
        raise S.RuleError("err_comment_required")
    with transaction():
        if action == "approve":
            execute("UPDATE deed_requests SET status='open', reviewed_by=?, reviewed_at=? WHERE request_id=?",
                    (admin["user_id"], now_str(), request_id))
            _mail(req, "mail_deed_open_subject", "mail_deed_open_body")
            for (uid,) in query("""SELECT c.user_id FROM coordinators c JOIN organizations o USING (org_id)
                                   WHERE o.city_id=? AND o.status='verified' AND o.deleted_at IS NULL""", (req["city_id"],)):
                notify(uid, "n_deed_new", url_for("org.deeds"), title=req["title"])
        else:
            execute("""UPDATE deed_requests SET status='rejected', reject_reason=?, reviewed_by=?, reviewed_at=?, closed_at=?
                       WHERE request_id=?""", (reason.strip(), admin["user_id"], now_str(), now_str(), request_id))
            _mail(req, "mail_deed_rejected_subject", "mail_deed_rejected_body", reason=reason.strip())
        if req["user_id"]:
            notify(req["user_id"], "n_deed_" + ("open" if action == "approve" else "rejected"), url_for("public.deeds_mine"), title=req["title"])
        audit("deed_" + action, "deed_requests", request_id, "pending", reason or action)


def _event_start(req):
    if req["when_kind"] == "on" and req["when_date"]:
        day = datetime.strptime(req["when_date"], "%Y-%m-%d")
    elif req["when_kind"] == "by" and req["when_date"]:
        day = max(datetime.strptime(req["when_date"], "%Y-%m-%d") - timedelta(days=2), datetime.now() + timedelta(days=3))
    else:
        day = datetime.now() + timedelta(days=7)
    start = day.replace(hour=11, minute=0, second=0, microsecond=0)
    if start <= datetime.now() + timedelta(hours=2):
        start = (datetime.now() + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
    return start


def take(user, coordinator, org, request_id):
    req = get(request_id)
    if not req or req["status"] != "open":
        raise S.RuleError("rule_deed_not_open")
    if org["status"] != "verified":
        raise S.RuleError("rule_org_not_verified")
    start = _event_start(req)
    fmt = "%Y-%m-%d %H:%M"
    summary = req["description"].strip().split("\n")[0]
    summary = summary if len(summary) <= 160 else summary[:157].rsplit(" ", 1)[0] + "…"
    with transaction(immediate=True):
        if scalar("SELECT status FROM deed_requests WHERE request_id=?", (request_id,)) != "open":
            raise S.RuleError("rule_deed_not_open")
        eid = execute("""INSERT INTO events (org_id, coordinator_id, direction_id, city_id, title, summary, description,
            address, starts_at, ends_at, registration_deadline, max_volunteers, min_age, requires_approval, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,14,1,'draft')""",
                      (org["org_id"], coordinator["coordinator_id"], req["direction_id"], req["city_id"], req["title"],
                       summary, req["description"], req["area"], start.strftime(fmt),
                       (start + timedelta(hours=3)).strftime(fmt), (start - timedelta(days=1)).strftime(fmt),
                       req["people_needed"] or 10))
        execute("""UPDATE deed_requests SET status='taken', taken_org_id=?, taken_by=?, taken_at=?, event_id=?
                   WHERE request_id=?""", (org["org_id"], user["user_id"], now_str(), eid, request_id))
        _mail(req, "mail_deed_taken_subject", "mail_deed_taken_body", org=org["name"])
        if req["user_id"]:
            notify(req["user_id"], "n_deed_taken", url_for("public.deeds_mine"), title=req["title"], org=org["name"])
        audit("deed_taken", "deed_requests", request_id, "open", org["name"])
    return eid


def _reopen(req, user=None):
    execute("""UPDATE deed_requests SET status='open', taken_org_id=NULL, taken_by=NULL, taken_at=NULL, event_id=NULL
               WHERE request_id=?""", (req["request_id"],))
    ev = query("SELECT * FROM events WHERE event_id=?", (req["event_id"],), one=True) if req["event_id"] else None
    if ev and ev["status"] == "draft" and not ev["deleted_at"]:
        execute("UPDATE events SET deleted_at=?, deleted_by=? WHERE event_id=?",
                (now_str(), user["user_id"] if user else None, ev["event_id"]))


def release(user, org_id, request_id):
    req = get(request_id)
    if not req or req["status"] != "taken" or req["taken_org_id"] != org_id:
        raise S.RuleError("rule_not_found")
    with transaction():
        _reopen(req, user)
        audit("deed_released", "deed_requests", request_id, "taken", "open")


def refresh():
    today = date.today().isoformat()
    limit = (datetime.now() - timedelta(days=TAKE_DAYS)).strftime("%Y-%m-%d %H:%M")
    for req in query("""SELECT d.*, e.status AS ev_status, e.deleted_at AS ev_deleted FROM deed_requests d
                        LEFT JOIN events e ON e.event_id = d.event_id WHERE d.status='taken'"""):
        if req["ev_status"] in ("published", "completed") and not req["ev_deleted"]:
            with transaction():
                execute("UPDATE deed_requests SET status='done', closed_at=? WHERE request_id=?",
                        (now_str(), req["request_id"]))
                link = url_for("public.event_detail", event_id=req["event_id"], _external=True)
                _mail(req, "mail_deed_done_subject", "mail_deed_done_body", link,
                      org=scalar("SELECT name FROM organizations WHERE org_id=?", (req["taken_org_id"],)))
                if req["user_id"]:
                    notify(req["user_id"], "n_deed_done", url_for("public.event_detail", event_id=req["event_id"]),
                           title=req["title"])
        elif req["taken_at"] <= limit or not req["event_id"] or req["ev_deleted"] or req["ev_status"] == "cancelled":
            with transaction():
                _reopen(req)
                audit("deed_auto_released", "deed_requests", req["request_id"], "taken", "open")
    with transaction():
        for req in query("""SELECT * FROM deed_requests WHERE status IN ('open','pending','unconfirmed')
                            AND when_date IS NOT NULL AND when_date < ?""", (today,)):
            execute("UPDATE deed_requests SET status='expired', closed_at=? WHERE request_id=?",
                    (now_str(), req["request_id"]))
            if req["status"] != "unconfirmed":
                _mail(req, "mail_deed_expired_subject", "mail_deed_expired_body")


LIST_SQL = """SELECT d.*, c.name_en AS city_name_en, c.name_ru AS city_name_ru, c.name_kk AS city_name_kk,
    dr.slug AS dir_slug, dr.name_en AS dir_name_en, dr.name_ru AS dir_name_ru, dr.name_kk AS dir_name_kk,
    dr.icon AS dir_icon, dr.tone AS dir_tone, e.status AS ev_status
    FROM deed_requests d JOIN cities c USING (city_id) JOIN directions dr USING (direction_id)
    LEFT JOIN events e ON e.event_id = d.event_id"""


def org_list(org, tab, city_only=True):
    if tab == "ours":
        return query(LIST_SQL + " WHERE d.taken_org_id=? AND d.status IN ('taken','done') ORDER BY d.taken_at DESC",
                     (org["org_id"],))
    sql, args = LIST_SQL + " WHERE d.status='open'", []
    if city_only:
        sql += " AND d.city_id=?"
        args.append(org["city_id"])
    return query(sql + " ORDER BY d.when_date IS NULL, d.when_date, d.created_at DESC", args)


def org_counts(org):
    return dict(open_city=scalar("SELECT COUNT(*) FROM deed_requests WHERE status='open' AND city_id=?", (org["city_id"],)),
                open_all=scalar("SELECT COUNT(*) FROM deed_requests WHERE status='open'"),
                ours=scalar("SELECT COUNT(*) FROM deed_requests WHERE taken_org_id=? AND status IN ('taken','done')",
                            (org["org_id"],)))


def admin_list(tab):
    where = {"pending": "d.status='pending'", "open": "d.status IN ('open','taken')",
             "closed": "d.status IN ('done','rejected','expired','withdrawn','unconfirmed')"}.get(tab, "d.status='pending'")
    return query(LIST_SQL.replace("e.status AS ev_status", "e.status AS ev_status, o.name AS org_name")
                 .replace("LEFT JOIN events e", "LEFT JOIN organizations o ON o.org_id = d.taken_org_id LEFT JOIN events e")
                 + f" WHERE {where} ORDER BY d.created_at DESC LIMIT 100")


def queue_count():
    return scalar("SELECT COUNT(*) FROM deed_requests WHERE status='pending'")
