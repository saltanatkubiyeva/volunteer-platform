import json
import os
import secrets
from datetime import datetime

from flask import current_app, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import services as S
from .core import audit, now_str
from .db import execute, query, transaction

DELETED_NAME = "Deleted user"
DELETED_PHONE = "+70000000000"


def _rows(sql, args):
    return [dict(r) for r in query(sql, args)]


def export_data(user):
    uid = user["user_id"]
    data = {
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "platform": "DEMEU",
        "account": _rows("""SELECT user_id, email, role, preferred_lang, created_at, last_login_at
                            FROM users WHERE user_id=?""", (uid,))[0],
    }
    v = query("SELECT volunteer_id FROM volunteers WHERE user_id=?", (uid,), one=True)
    if v:
        vid = v["volunteer_id"]
        data["profile"] = _rows("""SELECT v.full_name, v.phone, v.birth_date, c.name_en AS city, v.about, v.skills,
            v.is_public, v.show_contacts, v.created_at FROM volunteers v JOIN cities c USING (city_id)
            WHERE v.volunteer_id=?""", (vid,))[0]
        data["directions"] = [r["name_en"] for r in query("""SELECT d.name_en FROM volunteer_directions vd
            JOIN directions d USING (direction_id) WHERE vd.volunteer_id=? ORDER BY d.direction_id""", (vid,))]
        data["subscriptions"] = _rows("""SELECT COALESCE(c.name_en, d.name_en) AS name,
            CASE WHEN s.city_id IS NOT NULL THEN 'city' ELSE 'direction' END AS type, s.created_at
            FROM subscriptions s LEFT JOIN cities c USING (city_id) LEFT JOIN directions d USING (direction_id)
            WHERE s.volunteer_id=?""", (vid,))
        data["applications"] = _rows("""SELECT e.title AS event, o.name AS organization, e.starts_at, e.ends_at,
            r.status, r.motivation, r.applied_at, r.decided_at, r.hours_confirmed, r.is_team_lead,
            sh.title AS shift FROM registrations r JOIN events e USING (event_id) JOIN organizations o ON o.org_id=e.org_id
            LEFT JOIN event_shifts sh ON sh.shift_id=r.shift_id WHERE r.volunteer_id=? ORDER BY e.starts_at""", (vid,))
        data["waiting_list"] = _rows("""SELECT e.title AS event, e.starts_at, w.joined_at FROM waitlist w
            JOIN events e USING (event_id) WHERE w.volunteer_id=?""", (vid,))
        data["total_hours"] = S.total_hours(vid)
        data["certificates"] = _rows("""SELECT ce.type, ce.code, ce.issued_at, ce.milestone_hours, e.title AS event
            FROM certificates ce LEFT JOIN registrations r ON r.registration_id=ce.registration_id
            LEFT JOIN events e ON e.event_id=r.event_id
            WHERE ce.volunteer_id=? OR r.volunteer_id=? ORDER BY ce.issued_at""", (vid, vid))
        for c in data["certificates"]:
            c["verify_url"] = url_for("public.verify", code=c["code"], _external=True)
        data["my_reviews_of_events"] = _rows("""SELECT e.title AS event, f.rating, f.comment, f.created_at
            FROM feedback f JOIN registrations r USING (registration_id) JOIN events e USING (event_id)
            WHERE r.volunteer_id=?""", (vid,))
        data["feedback_from_organizations"] = _rows("""SELECT o.name AS organization, e.title AS event, vf.is_thanks,
            vf.is_reliable, vf.good_with_children, vf.comment, vf.created_at FROM volunteer_feedback vf
            JOIN registrations r USING (registration_id) JOIN events e USING (event_id)
            JOIN organizations o ON o.org_id=e.org_id WHERE r.volunteer_id=?""", (vid,))
        data["documents"] = _rows("""SELECT s.name_en AS document, vs.status, vs.expires_at, vs.uploaded_at,
            vs.review_comment FROM volunteer_skills vs JOIN skills s USING (skill_id) WHERE vs.volunteer_id=?""", (vid,))
        data["parental_consents"] = _rows("""SELECT parent_name, parent_phone, status, uploaded_at, review_comment
            FROM consents WHERE volunteer_id=?""", (vid,))
    c = query("SELECT coordinator_id FROM coordinators WHERE user_id=?", (uid,), one=True)
    if c:
        data["coordinator"] = _rows("""SELECT c.full_name, c.position, c.phone, c.is_owner, o.name AS organization
            FROM coordinators c JOIN organizations o USING (org_id) WHERE c.coordinator_id=?""",
                                    (c["coordinator_id"],))[0]
        data["events_coordinated"] = _rows("""SELECT title, starts_at, status FROM events WHERE coordinator_id=?
            ORDER BY starts_at""", (c["coordinator_id"],))
    data["photos_uploaded"] = _rows("""SELECT e.title AS event, p.status, p.created_at FROM event_photos p
        JOIN events e USING (event_id) WHERE p.user_id=?""", (uid,))
    data["reports_sent"] = _rows("""SELECT COALESCE(e.title, o.name) AS about, c.reason, c.details, c.status, c.created_at
        FROM complaints c LEFT JOIN events e USING (event_id) LEFT JOIN organizations o ON o.org_id=c.org_id
        WHERE c.reporter_id=?""", (uid,))
    data["notifications"] = _rows("""SELECT kind, params, link, is_read, created_at FROM notifications
        WHERE user_id=? ORDER BY created_at""", (uid,))
    for n in data["notifications"]:
        try:
            n["params"] = json.loads(n["params"] or "{}")
        except ValueError:
            pass
    audit("data_exported", "users", uid)
    return data


def _still_used(path):
    return bool(query("""SELECT 1 FROM volunteers WHERE avatar_path=? UNION ALL SELECT 1 FROM volunteer_skills WHERE file_path=?
        UNION ALL SELECT 1 FROM consents WHERE file_path=? UNION ALL SELECT 1 FROM event_photos WHERE file_path=?
        UNION ALL SELECT 1 FROM organizations WHERE logo_path=? UNION ALL SELECT 1 FROM events WHERE cover_path=? LIMIT 1""",
                      (path,) * 6, one=True))


def delete_account(user, password):
    if user["role"] != "volunteer":
        raise S.RuleError("rule_delete_volunteers_only")
    if not check_password_hash(user["password_hash"], password or ""):
        raise S.RuleError("err_current_password")
    v = query("SELECT * FROM volunteers WHERE user_id=?", (user["user_id"],), one=True)
    vid, uid, now = v["volunteer_id"], user["user_id"], now_str()
    files = [v["avatar_path"]]
    files += [r["file_path"] for r in query("SELECT file_path FROM volunteer_skills WHERE volunteer_id=?", (vid,))]
    files += [r["file_path"] for r in query("SELECT file_path FROM consents WHERE volunteer_id=?", (vid,))]
    files += [r["file_path"] for r in query("SELECT file_path FROM event_photos WHERE user_id=?", (uid,))]
    freed = [r["event_id"] for r in query("""SELECT r.event_id FROM registrations r JOIN events e USING (event_id)
        WHERE r.volunteer_id=? AND r.status IN ('pending','approved') AND e.starts_at > ?""", (vid, now))]
    with transaction(immediate=True):
        execute("""UPDATE registrations SET status='cancelled', decided_at=?, decision_note='account deleted'
                   WHERE volunteer_id=? AND status IN ('pending','approved')
                   AND event_id IN (SELECT event_id FROM events WHERE starts_at > ?)""", (now, vid, now))
        execute("UPDATE registrations SET motivation=NULL WHERE volunteer_id=?", (vid,))
        execute("""UPDATE feedback SET comment=NULL WHERE registration_id IN
                   (SELECT registration_id FROM registrations WHERE volunteer_id=?)""", (vid,))
        for table in ("waitlist", "subscriptions", "volunteer_directions", "volunteer_skills", "consents"):
            execute(f"DELETE FROM {table} WHERE volunteer_id=?", (vid,))
        for table in ("event_photos", "notifications", "password_resets", "outbox", "announcement_hidden"):
            execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
        execute("""UPDATE volunteers SET full_name=?, phone=?, birth_date='1900-01-01', about=NULL, skills=NULL,
                   avatar_path=NULL, is_public=0, show_contacts=0 WHERE volunteer_id=?""",
                (DELETED_NAME, DELETED_PHONE, vid))
        execute("""UPDATE users SET email=?, password_hash=?, is_active=0, last_login_at=NULL, deleted_at=?
                   WHERE user_id=?""", (f"deleted-{uid}@deleted.demeu.kz", generate_password_hash(secrets.token_hex(32)),
                                         now, uid))
        audit("account_deleted", "users", uid, None, "anonymized")
    for event_id in sorted(set(freed)):
        S.promote_waitlist(event_id)
    for path in files:
        if path and not _still_used(path):
            try:
                os.remove(os.path.join(current_app.config["UPLOAD_DIR"], path))
            except OSError:
                pass
