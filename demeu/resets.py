import hashlib
import secrets
from datetime import datetime, timedelta

from flask import url_for

from .core import _, audit, notify, now_str
from .db import execute, query, scalar, transaction

TOKEN_HOURS = 1
MAX_PER_HOUR = 3


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def mask_email(email):
    local, _sep, domain = (email or "").partition("@")
    if len(local) <= 2:
        hidden = local[:1] + "*" * max(1, len(local) - 1)
    else:
        hidden = local[0] + "****" + local[-1]
    return f"{hidden}@{domain}" if domain else hidden


def request_reset(email, requested_by=None):
    user = query("SELECT * FROM users WHERE email=?", (email,), one=True)
    if not user:
        return "unknown"
    if not user["is_active"]:
        return "blocked"
    hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    if requested_by is None and scalar("SELECT COUNT(*) FROM password_resets WHERE user_id=? AND created_at >= ?",
                                       (user["user_id"], hour_ago)) >= MAX_PER_HOUR:
        return "limited"
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    link = url_for("auth.reset_password", token=token, _external=True)
    with transaction():
        execute("""INSERT INTO password_resets (user_id, token_hash, created_at, expires_at, requested_by)
                   VALUES (?,?,?,?,?)""",
                (user["user_id"], token_hash(token), now.strftime("%Y-%m-%d %H:%M:%S"),
                 (now + timedelta(hours=TOKEN_HOURS)).strftime("%Y-%m-%d %H:%M:%S"), requested_by))
        execute("INSERT INTO outbox (user_id, to_email, subject, body, link) VALUES (?,?,?,?,?)",
                (user["user_id"], user["email"], _("mail_reset_subject"),
                 _("mail_reset_body", link=link, h=TOKEN_HOURS), link))
    return "sent"


def find_valid(token):
    if not token or len(token) > 100:
        return None
    return query("""SELECT pr.*, u.email FROM password_resets pr JOIN users u USING (user_id)
                    WHERE pr.token_hash=? AND pr.used_at IS NULL AND pr.expires_at > ? AND u.is_active=1""",
                 (token_hash(token), datetime.now().strftime("%Y-%m-%d %H:%M:%S")), one=True)


def complete_reset(token, new_hash):
    with transaction(immediate=True):
        row = find_valid(token)
        if not row:
            return None
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        execute("UPDATE users SET password_hash=? WHERE user_id=?", (new_hash, row["user_id"]))
        execute("UPDATE password_resets SET used_at=? WHERE user_id=? AND used_at IS NULL", (stamp, row["user_id"]))
        audit("password_reset_by_link", "users", row["user_id"])
        notify(row["user_id"], "n_password_changed", url_for("auth.settings"))
    return row
