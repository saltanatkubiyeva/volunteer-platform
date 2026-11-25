import os

from flask import current_app, url_for

from . import services as S
from .core import IMAGE_EXT, audit, notify, now_str, save_upload
from .db import execute, query, scalar, transaction

MAX_PER_PERSON = 10
HIDE_REASONS = ("children", "ads", "unrelated", "quality", "other")
REPORT_REASONS = ("fake", "unsafe", "inappropriate", "fraud", "other")


def can_upload(user, ev):
    if not user or not ev or ev["status"] not in ("published", "completed") or ev["ends_at"] > now_str():
        return False
    if user["role"] == "coordinator":
        return bool(scalar("SELECT 1 FROM coordinators WHERE user_id=? AND org_id=?", (user["user_id"], ev["org_id"])))
    if user["role"] == "volunteer":
        return bool(scalar("""SELECT 1 FROM registrations r JOIN volunteers v USING (volunteer_id)
                              WHERE v.user_id=? AND r.event_id=? AND r.status='attended'""",
                           (user["user_id"], ev["event_id"])))
    return False


def uploaded_count(user_id, event_id):
    return scalar("SELECT COUNT(*) FROM event_photos WHERE user_id=? AND event_id=?", (user_id, event_id))


def upload(user, ev, files):
    if not can_upload(user, ev):
        raise S.RuleError("rule_photo_not_allowed")
    files = [f for f in files if f and f.filename]
    if not files:
        raise S.RuleError("err_photo_choose")
    left = MAX_PER_PERSON - uploaded_count(user["user_id"], ev["event_id"])
    if len(files) > left:
        raise S.RuleError("rule_photo_limit", n=MAX_PER_PERSON, left=max(left, 0))
    saved = []
    try:
        for f in files:
            saved.append(save_upload(f, IMAGE_EXT, "photos"))
    except ValueError as e:
        for path in saved:
            _remove_file(path)
        raise S.RuleError(str(e))
    with transaction():
        for path in saved:
            execute("INSERT INTO event_photos (event_id, user_id, file_path) VALUES (?,?,?)",
                    (ev["event_id"], user["user_id"], path))
        audit("photos_uploaded", "events", ev["event_id"], None, str(len(saved)))
    return len(saved)


def _remove_file(path):
    try:
        os.remove(os.path.join(current_app.config["UPLOAD_DIR"], path))
    except OSError:
        pass


GALLERY_SELECT = """SELECT p.*, COALESCE(v.full_name, o.name) AS author, v.volunteer_id,
       (SELECT COUNT(*) FROM photo_reports pr WHERE pr.photo_id=p.photo_id AND pr.status='new') AS reports
FROM event_photos p
LEFT JOIN volunteers v ON v.user_id = p.user_id
LEFT JOIN coordinators c ON c.user_id = p.user_id
LEFT JOIN organizations o ON o.org_id = c.org_id
"""


def gallery(event_id):
    return query(GALLERY_SELECT + " WHERE p.event_id=? AND p.status='visible' ORDER BY p.created_at, p.photo_id",
                 (event_id,))


def get_photo(photo_id):
    return query(GALLERY_SELECT + " WHERE p.photo_id=?", (photo_id,), one=True)


def delete(user, photo_id):
    p = get_photo(photo_id)
    if not p or (p["user_id"] != user["user_id"] and user["role"] != "admin"):
        raise S.RuleError("rule_not_found")
    with transaction():
        execute("DELETE FROM event_photos WHERE photo_id=?", (photo_id,))
        audit("photo_deleted", "event_photos", photo_id, p["file_path"], None)
    _remove_file(p["file_path"])
    return p["event_id"]


def report(user, photo_id, reason, details):
    p = get_photo(photo_id)
    if not user or not p or p["status"] != "visible" or user["role"] == "admin" or p["user_id"] == user["user_id"]:
        raise S.RuleError("rule_cannot_report")
    if reason not in REPORT_REASONS:
        raise S.RuleError("err_report_reason")
    if reason == "other" and len(details or "") < 10:
        raise S.RuleError("err_report_details")
    if scalar("SELECT 1 FROM photo_reports WHERE photo_id=? AND reporter_id=?", (photo_id, user["user_id"])):
        raise S.RuleError("rule_report_already")
    with transaction():
        execute("INSERT INTO photo_reports (photo_id, reporter_id, reason, details) VALUES (?,?,?,?)",
                (photo_id, user["user_id"], reason, details or None))
        for (admin_id,) in query("SELECT user_id FROM users WHERE role='admin' AND is_active=1"):
            notify(admin_id, "n_admin_photo_report", url_for("admin.photos"))
    return p["event_id"]


def review(admin, photo_id, action, reason=None):
    p = get_photo(photo_id)
    if not p or action not in ("keep", "hide", "show"):
        raise S.RuleError("rule_not_found")
    if action == "hide" and reason not in HIDE_REASONS:
        raise S.RuleError("err_hide_reason")
    now = now_str()
    link = url_for("public.event_detail", event_id=p["event_id"])
    title = scalar("SELECT title FROM events WHERE event_id=?", (p["event_id"],))
    with transaction():
        if action == "hide":
            execute("""UPDATE event_photos SET status='hidden', hide_reason=?, reviewed_by=?, reviewed_at=?
                       WHERE photo_id=?""", (reason, admin["user_id"], now, photo_id))
            if p["user_id"] and p["status"] == "visible":
                notify(p["user_id"], "n_photo_hidden", link, event=title, reason=reason)
        elif action == "show":
            execute("""UPDATE event_photos SET status='visible', hide_reason=NULL, reviewed_by=?, reviewed_at=?
                       WHERE photo_id=?""", (admin["user_id"], now, photo_id))
        else:
            execute("UPDATE event_photos SET reviewed_by=?, reviewed_at=? WHERE photo_id=?",
                    (admin["user_id"], now, photo_id))
        decision = "resolved" if action == "hide" else "dismissed"
        for r in query("SELECT * FROM photo_reports WHERE photo_id=? AND status='new'", (photo_id,)):
            execute("UPDATE photo_reports SET status=?, handled_at=? WHERE report_id=?", (decision, now, r["report_id"]))
            notify(r["reporter_id"], "n_report_resolved" if decision == "resolved" else "n_report_reviewed", link,
                   name=title)
        audit("photo_" + action, "event_photos", photo_id, p["status"], reason or action)


def queue_count():
    return scalar("""SELECT COUNT(*) FROM event_photos p WHERE p.reviewed_at IS NULL
                     OR EXISTS (SELECT 1 FROM photo_reports r WHERE r.photo_id=p.photo_id AND r.status='new')""")
