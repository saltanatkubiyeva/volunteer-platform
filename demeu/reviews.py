import re

from flask import url_for

from . import services as S
from .core import audit, notify, now_str
from .db import execute, query, scalar, transaction

REPORT_REASONS = ("offensive", "spam", "personal", "fake", "other")
HIDE_REASONS = ("offensive", "spam", "personal", "fake", "other")


def banned_words():
    return [r["word"] for r in query("SELECT word FROM banned_words ORDER BY word")]


def find_banned(text, words=None):
    words = banned_words() if words is None else words
    if not text or not words:
        return []
    pattern = re.compile(r"(?<!\w)(" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")",
                         re.IGNORECASE)
    found = []
    for m in pattern.finditer(text):
        w = m.group(1).lower()
        if w not in found:
            found.append(w)
    return found


def submit(registration_id, rating, comment):
    found = find_banned(comment)
    status = "pending" if found else "published"
    with transaction():
        fid = execute("""INSERT INTO feedback (registration_id, rating, comment, status, is_hidden, flagged_words)
                         VALUES (?,?,?,?,?,?)""",
                      (registration_id, rating, comment, status, 0 if status == "published" else 1,
                       ", ".join(found) or None))
        if found:
            for (admin_id,) in query("SELECT user_id FROM users WHERE role='admin' AND is_active=1"):
                notify(admin_id, "n_admin_review_pending", url_for("admin.reviews"))
        audit("review_" + status, "feedback", fid, None, ", ".join(found) or status)
    return status


def get(feedback_id):
    return query("""SELECT f.*, v.user_id AS author_id, e.title, e.event_id FROM feedback f
                    JOIN registrations r USING (registration_id) JOIN volunteers v USING (volunteer_id)
                    JOIN events e USING (event_id) WHERE f.feedback_id=?""", (feedback_id,), one=True)


def can_report(user, review):
    return bool(user and review and user["role"] != "admin" and review["author_id"] != user["user_id"]
                and review["status"] == "published")


def report(user, feedback_id, reason, details):
    f = get(feedback_id)
    if not can_report(user, f):
        raise S.RuleError("rule_cannot_report")
    if reason not in REPORT_REASONS:
        raise S.RuleError("err_report_reason")
    if reason == "other" and len(details or "") < 10:
        raise S.RuleError("err_report_details")
    if scalar("SELECT 1 FROM review_reports WHERE feedback_id=? AND reporter_id=?", (feedback_id, user["user_id"])):
        raise S.RuleError("rule_report_already")
    with transaction():
        execute("INSERT INTO review_reports (feedback_id, reporter_id, reason, details) VALUES (?,?,?,?)",
                (feedback_id, user["user_id"], reason, details or None))
        for (admin_id,) in query("SELECT user_id FROM users WHERE role='admin' AND is_active=1"):
            notify(admin_id, "n_admin_review_report", url_for("admin.reviews"))
    return f["event_id"]


def review(admin, feedback_id, action, reason=None):
    f = get(feedback_id)
    if not f or action not in ("publish", "hide"):
        raise S.RuleError("rule_not_found")
    if action == "hide" and reason not in HIDE_REASONS:
        raise S.RuleError("err_hide_reason")
    now = now_str()
    link = url_for("public.event_detail", event_id=f["event_id"])
    with transaction():
        if action == "hide":
            execute("""UPDATE feedback SET status='hidden', is_hidden=1, hide_reason=?, reviewed_by=?, reviewed_at=?
                       WHERE feedback_id=?""", (reason, admin["user_id"], now, feedback_id))
            if f["status"] != "hidden":
                notify(f["author_id"], "n_review_hidden", link, event=f["title"], reason=reason)
        else:
            execute("""UPDATE feedback SET status='published', is_hidden=0, hide_reason=NULL, reviewed_by=?, reviewed_at=?
                       WHERE feedback_id=?""", (admin["user_id"], now, feedback_id))
            if f["status"] == "pending":
                notify(f["author_id"], "n_review_published", link, event=f["title"])
        decision = "resolved" if action == "hide" else "dismissed"
        for r in query("SELECT * FROM review_reports WHERE feedback_id=? AND status='new'", (feedback_id,)):
            execute("UPDATE review_reports SET status=?, handled_at=? WHERE report_id=?", (decision, now, r["report_id"]))
            notify(r["reporter_id"], "n_report_resolved" if decision == "resolved" else "n_report_reviewed", link,
                   name=f["title"])
        audit("review_" + action, "feedback", feedback_id, f["status"], reason or action)


QUEUE_WHERE = """(f.status='pending' OR EXISTS (SELECT 1 FROM review_reports rr
                 WHERE rr.feedback_id=f.feedback_id AND rr.status='new'))"""


def queue_count():
    return scalar(f"SELECT COUNT(*) FROM feedback f WHERE {QUEUE_WHERE}")


def admin_rows(tab):
    where = {"queue": QUEUE_WHERE, "hidden": "f.status='hidden'"}.get(tab, QUEUE_WHERE)
    rows = query(f"""SELECT f.*, v.full_name, u.email, e.title, e.event_id, o.name AS org_name,
        (SELECT COUNT(*) FROM review_reports rr WHERE rr.feedback_id=f.feedback_id AND rr.status='new') AS reports
        FROM feedback f JOIN registrations r USING (registration_id) JOIN volunteers v USING (volunteer_id)
        JOIN users u ON u.user_id = v.user_id JOIN events e USING (event_id) JOIN organizations o ON o.org_id = e.org_id
        WHERE {where} ORDER BY f.status='pending' DESC, reports DESC, f.created_at DESC LIMIT 100""")
    reports = {}
    for r in query("""SELECT rr.*, u.email FROM review_reports rr JOIN users u ON u.user_id = rr.reporter_id
                      WHERE rr.status='new' ORDER BY rr.created_at"""):
        reports.setdefault(r["feedback_id"], []).append(r)
    return rows, reports


def add_word(admin, word):
    word = (word or "").strip().lower()
    if len(word) < 3 or len(word) > 40:
        raise S.RuleError("err_banned_word")
    if scalar("SELECT 1 FROM banned_words WHERE word=?", (word,)):
        raise S.RuleError("err_banned_word_exists")
    execute("INSERT INTO banned_words (word, created_by) VALUES (?,?)", (word, admin["user_id"]))
    audit("banned_word_added", "banned_words", None, None, word)


def remove_word(admin, word_id):
    w = query("SELECT * FROM banned_words WHERE word_id=?", (word_id,), one=True)
    if w:
        execute("DELETE FROM banned_words WHERE word_id=?", (word_id,))
        audit("banned_word_removed", "banned_words", word_id, w["word"], None)
