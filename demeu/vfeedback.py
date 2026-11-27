from flask import url_for

from . import services as S
from .core import audit, notify, now_str
from .db import execute, query, transaction

TAGS = ("is_thanks", "is_reliable", "good_with_children")


def save(coordinator, registration_id, tags, comment):
    reg = query("""SELECT r.*, e.org_id, e.title, e.event_id, v.user_id AS vol_user, o.name AS org_name
                   FROM registrations r JOIN events e USING (event_id) JOIN volunteers v USING (volunteer_id)
                   JOIN organizations o ON o.org_id = e.org_id WHERE r.registration_id=?""", (registration_id,), one=True)
    if not reg or not S.manages(coordinator, reg["event_id"]):
        raise S.RuleError("rule_not_found")
    if reg["status"] != "attended":
        raise S.RuleError("rule_feedback_attended")
    flags = {t: 1 if t in tags else 0 for t in TAGS}
    comment = (comment or "").strip() or None
    if not any(flags.values()) and not comment:
        raise S.RuleError("err_feedback_empty")
    old = query("SELECT * FROM volunteer_feedback WHERE registration_id=?", (registration_id,), one=True)
    with transaction():
        if old:
            execute("""UPDATE volunteer_feedback SET is_thanks=?, is_reliable=?, good_with_children=?, comment=?,
                       coordinator_id=?, updated_at=? WHERE registration_id=?""",
                    (flags["is_thanks"], flags["is_reliable"], flags["good_with_children"], comment,
                     coordinator["coordinator_id"], now_str(), registration_id))
        else:
            execute("""INSERT INTO volunteer_feedback (registration_id, coordinator_id, is_thanks, is_reliable,
                       good_with_children, comment) VALUES (?,?,?,?,?,?)""",
                    (registration_id, coordinator["coordinator_id"], flags["is_thanks"], flags["is_reliable"],
                     flags["good_with_children"], comment))
        if not old or (flags["is_thanks"] and not old["is_thanks"]):
            notify(reg["vol_user"], "n_feedback_thanks" if flags["is_thanks"] else "n_feedback_new",
                   url_for("public.volunteer_profile", volunteer_id=reg["volunteer_id"]),
                   org=reg["org_name"], event=reg["title"])
        audit("volunteer_feedback", "registrations", registration_id, "updated" if old else None,
              ",".join(t for t in TAGS if flags[t]) or "comment")


def for_event(event_id):
    return {r["registration_id"]: r for r in query("""SELECT f.* FROM volunteer_feedback f
        JOIN registrations r USING (registration_id) WHERE r.event_id=?""", (event_id,))}


def summary(volunteer_ids):
    ids = sorted({int(v) for v in volunteer_ids})
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out = {}
    for r in query(f"""SELECT r.volunteer_id, f.*, o.name AS org_name, e.title FROM volunteer_feedback f
                       JOIN registrations r USING (registration_id) JOIN events e USING (event_id)
                       JOIN organizations o ON o.org_id = e.org_id
                       WHERE r.volunteer_id IN ({marks}) ORDER BY e.starts_at DESC""", ids):
        s = out.setdefault(r["volunteer_id"], dict(total=0, thanks=0, reliable=0, children=0, last=None))
        s["total"] += 1
        s["thanks"] += r["is_thanks"]
        s["reliable"] += r["is_reliable"]
        s["children"] += r["good_with_children"]
        if s["last"] is None and r["comment"]:
            s["last"] = r
    return out


def for_volunteer(volunteer_id):
    return query("""SELECT f.*, e.title, e.event_id, e.starts_at, o.name AS org_name, o.org_id, o.logo_path AS org_logo
        FROM volunteer_feedback f JOIN registrations r USING (registration_id) JOIN events e USING (event_id)
        JOIN organizations o ON o.org_id = e.org_id WHERE r.volunteer_id=? ORDER BY e.starts_at DESC""",
                 (volunteer_id,))
