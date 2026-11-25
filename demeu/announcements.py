from flask import g, session

from . import services as S
from .core import audit, notify, now_str
from .db import execute, query, transaction

AUDIENCES = ("all", "volunteers", "coordinators", "city")
TONES = ("info", "warning")


def user_city():
    if g.get("volunteer"):
        return g.volunteer["city_id"]
    if g.get("org"):
        return g.org["city_id"]
    return None


def visible_for_current_user():
    rows = query("SELECT * FROM announcements WHERE starts_at <= ? AND ends_at > ? ORDER BY tone='warning' DESC, starts_at DESC",
                 (now_str(), now_str()))
    hidden = set(session.get("hidden_ann", []))
    if g.get("user"):
        hidden |= {r["announcement_id"] for r in query(
            "SELECT announcement_id FROM announcement_hidden WHERE user_id=?", (g.user["user_id"],))}
    out = []
    for a in rows:
        if a["announcement_id"] in hidden and a["tone"] != "warning":
            continue
        if a["audience"] == "volunteers" and not g.get("volunteer"):
            continue
        if a["audience"] == "coordinators" and not g.get("coordinator"):
            continue
        if a["audience"] == "city" and user_city() != a["city_id"]:
            continue
        out.append(a)
    return out


def dismiss(announcement_id):
    a = query("SELECT tone FROM announcements WHERE announcement_id=?", (announcement_id,), one=True)
    if not a or a["tone"] == "warning":
        return
    if g.get("user"):
        execute("INSERT OR IGNORE INTO announcement_hidden (user_id, announcement_id) VALUES (?, ?)",
                (g.user["user_id"], announcement_id))
        return
    hidden = [x for x in session.get("hidden_ann", []) if isinstance(x, int)]
    if announcement_id not in hidden:
        hidden = (hidden + [announcement_id])[-50:]
    session["hidden_ann"] = hidden


def recipients(audience, city_id):
    if audience == "volunteers":
        return query("SELECT u.user_id FROM users u WHERE u.role='volunteer' AND u.is_active=1")
    if audience == "coordinators":
        return query("SELECT u.user_id FROM users u WHERE u.role='coordinator' AND u.is_active=1")
    if audience == "city":
        return query("""SELECT u.user_id FROM users u JOIN volunteers v USING (user_id) WHERE u.is_active=1 AND v.city_id=?
                        UNION SELECT u.user_id FROM users u JOIN coordinators c USING (user_id)
                        JOIN organizations o USING (org_id) WHERE u.is_active=1 AND o.city_id=?""", (city_id, city_id))
    return query("SELECT user_id FROM users WHERE is_active=1 AND role <> 'admin'")


def create(admin, f, send):
    with transaction():
        aid = execute("""INSERT INTO announcements (text_en, text_ru, text_kk, tone, audience, city_id, link,
                         starts_at, ends_at, notified, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                      (f["text_en"], f["text_ru"], f["text_kk"], f["tone"], f["audience"],
                       f["city_id"] if f["audience"] == "city" else None, f["link"] or None,
                       f["starts_at"], f["ends_at"], 1 if send else 0, admin["user_id"]))
        sent = 0
        if send:
            for r in recipients(f["audience"], f["city_id"]):
                notify(r["user_id"], "n_announcement", f["link"] or None,
                       en=f["text_en"], ru=f["text_ru"], kk=f["text_kk"])
                sent += 1
        audit("announcement_created", "announcements", aid, None, f"{f['audience']}, notified {sent}")
    return sent


def end_now(admin, announcement_id):
    a = query("SELECT * FROM announcements WHERE announcement_id=?", (announcement_id,), one=True)
    if not a:
        raise S.RuleError("rule_not_found")
    now = now_str()
    with transaction():
        if a["starts_at"] >= now:
            execute("DELETE FROM announcements WHERE announcement_id=?", (announcement_id,))
        elif a["ends_at"] > now:
            execute("UPDATE announcements SET ends_at=? WHERE announcement_id=?", (now, announcement_id))
        audit("announcement_ended", "announcements", announcement_id, a["ends_at"], now)


def phase(a, now):
    if a["starts_at"] > now:
        return "scheduled"
    if a["ends_at"] <= now:
        return "ended"
    return "active"
