import json

from flask import g, url_for

from . import services as S
from .core import audit, notify, now_str
from .db import execute, query, scalar, transaction

FRIEND_MILESTONES = (20, 50, 100, 200)

PERSON = """v.volunteer_id, v.user_id, v.full_name, v.avatar_path, v.is_public, v.city_id,
    COALESCE((SELECT SUM(r.hours_confirmed) FROM registrations r WHERE r.volunteer_id = v.volunteer_id
              AND r.status='attended'), 0) AS hours"""


def short_name(row):
    parts = (row["full_name"] or "").split()
    if row["is_public"] or len(parts) < 2:
        return row["full_name"]
    return f"{parts[0]} {parts[-1][0]}."


def relation(me, other):
    if me == other:
        return dict(state="self")
    f = query("""SELECT * FROM friendships WHERE (requester_id=? AND addressee_id=?) OR (requester_id=? AND addressee_id=?)""",
              (me, other, other, me), one=True)
    if not f:
        return dict(state=None)
    if f["status"] == "accepted":
        return dict(state="friends", id=f["friendship_id"])
    return dict(state="sent" if f["requester_id"] == me else "received", id=f["friendship_id"])


def friend_ids(vid):
    return [r[0] for r in query("""SELECT CASE WHEN requester_id=? THEN addressee_id ELSE requester_id END
        FROM friendships WHERE status='accepted' AND (requester_id=? OR addressee_id=?)""", (vid, vid, vid))]


def are_friends(a, b):
    return relation(a, b)["state"] == "friends"


def _vol(vid):
    return query("""SELECT v.*, u.deleted_at FROM volunteers v JOIN users u USING (user_id)
                    WHERE v.volunteer_id=?""", (vid,), one=True)


def send(me, other_vid):
    other = _vol(other_vid)
    if not other or other["deleted_at"] or other_vid == me["volunteer_id"]:
        raise S.RuleError("rule_not_found")
    rel = relation(me["volunteer_id"], other_vid)
    if rel["state"] == "received":
        return accept(me, rel["id"])
    if rel["state"]:
        raise S.RuleError("rule_friend_exists")
    with transaction():
        fid = execute("INSERT INTO friendships (requester_id, addressee_id) VALUES (?,?)", (me["volunteer_id"], other_vid))
        notify(other["user_id"], "n_friend_request", url_for("volunteer.friends", tab="requests"), name=me["full_name"])
        audit("friend_request", "friendships", fid)
    return "sent"


def accept(me, friendship_id):
    f = query("SELECT * FROM friendships WHERE friendship_id=?", (friendship_id,), one=True)
    if not f or f["addressee_id"] != me["volunteer_id"] or f["status"] != "pending":
        raise S.RuleError("rule_not_found")
    with transaction():
        execute("UPDATE friendships SET status='accepted', accepted_at=? WHERE friendship_id=?", (now_str(), friendship_id))
        requester = _vol(f["requester_id"])
        notify(requester["user_id"], "n_friend_accepted", url_for("public.volunteer_profile", volunteer_id=me["volunteer_id"]),
               name=me["full_name"])
        audit("friend_accepted", "friendships", friendship_id)
    return "friends"


def remove(me, friendship_id):
    f = query("SELECT * FROM friendships WHERE friendship_id=?", (friendship_id,), one=True)
    if not f or me["volunteer_id"] not in (f["requester_id"], f["addressee_id"]):
        raise S.RuleError("rule_not_found")
    execute("DELETE FROM friendships WHERE friendship_id=?", (friendship_id,))
    audit("friend_removed" if f["status"] == "accepted" else "friend_request_closed", "friendships", friendship_id)


def friends(vid):
    ids = friend_ids(vid)
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return query(f"""SELECT {PERSON}, f.friendship_id FROM volunteers v
        JOIN friendships f ON f.status='accepted' AND ((f.requester_id=? AND f.addressee_id=v.volunteer_id)
                                                      OR (f.addressee_id=? AND f.requester_id=v.volunteer_id))
        WHERE v.volunteer_id IN ({marks}) ORDER BY v.full_name""", [vid, vid] + ids)


def requests(vid):
    incoming = query(f"""SELECT {PERSON}, f.friendship_id, f.created_at AS asked_at FROM friendships f
        JOIN volunteers v ON v.volunteer_id = f.requester_id WHERE f.addressee_id=? AND f.status='pending'
        ORDER BY f.created_at DESC""", (vid,))
    outgoing = query(f"""SELECT {PERSON}, f.friendship_id, f.created_at AS asked_at FROM friendships f
        JOIN volunteers v ON v.volunteer_id = f.addressee_id WHERE f.requester_id=? AND f.status='pending'
        ORDER BY f.created_at DESC""", (vid,))
    return incoming, outgoing


def incoming_count(vid):
    return scalar("SELECT COUNT(*) FROM friendships WHERE addressee_id=? AND status='pending'", (vid,))


def met(vid, limit=30):
    return query(f"""SELECT {PERSON}, COUNT(DISTINCT mine.event_id) AS shared,
        (SELECT e.title FROM events e JOIN registrations a ON a.event_id=e.event_id AND a.volunteer_id=v.volunteer_id
           AND a.status='attended' JOIN registrations b ON b.event_id=e.event_id AND b.volunteer_id=? AND b.status='attended'
           ORDER BY e.starts_at DESC LIMIT 1) AS last_event
        FROM registrations mine JOIN registrations them ON them.event_id = mine.event_id
        JOIN volunteers v ON v.volunteer_id = them.volunteer_id JOIN users u ON u.user_id = v.user_id
        WHERE mine.volunteer_id=? AND mine.status='attended' AND them.status='attended' AND them.volunteer_id<>?
          AND u.deleted_at IS NULL AND u.is_active=1
          AND NOT EXISTS (SELECT 1 FROM friendships f WHERE (f.requester_id=? AND f.addressee_id=v.volunteer_id)
                                                       OR (f.addressee_id=? AND f.requester_id=v.volunteer_id))
        GROUP BY v.volunteer_id ORDER BY shared DESC, v.full_name LIMIT ?""", (vid, vid, vid, vid, vid, limit))


def going(vid, event_ids=None):
    ids = friend_ids(vid)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    sql = f"""SELECT r.event_id, v.volunteer_id, v.full_name, v.avatar_path, v.is_public FROM registrations r
        JOIN volunteers v USING (volunteer_id) JOIN events e USING (event_id)
        WHERE r.volunteer_id IN ({marks}) AND v.share_plans=1 AND r.status IN ('approved','attended')
          AND e.deleted_at IS NULL"""
    args = list(ids)
    if event_ids is not None:
        if not event_ids:
            return {}
        sql += f" AND r.event_id IN ({','.join('?' * len(event_ids))})"
        args += list(event_ids)
    else:
        sql += " AND e.status='published' AND e.starts_at > ?"
        args.append(now_str())
    out = {}
    for r in query(sql + " ORDER BY v.full_name", args):
        out.setdefault(r["event_id"], []).append(dict(r, short=short_name(r)))
    return out


def going_for_cards():
    if not g.get("volunteer"):
        return {}
    if "friends_going" not in g:
        g.friends_going = going(g.volunteer["volunteer_id"])
    return g.friends_going


def upcoming_with_friends(vid, limit=6):
    plans = going(vid)
    if not plans:
        return []
    marks = ",".join("?" * len(plans))
    rows = query(S.EVENT_SELECT + f""" WHERE e.event_id IN ({marks}) AND {S.PUBLIC_WHERE} AND e.starts_at > ?
        ORDER BY e.starts_at LIMIT ?""", list(plans) + [now_str(), limit])
    mine = {r[0]: r[1] for r in query("SELECT event_id, status FROM registrations WHERE volunteer_id=?", (vid,))}
    return [dict(ev=ev, friends=plans[ev["event_id"]], my_status=mine.get(ev["event_id"])) for ev in rows]


def on_joined(volunteer_id, event_id):
    me = _vol(volunteer_id)
    if not me or not me["share_plans"]:
        return
    ev = S.get_event(event_id)
    if not ev or ev["status"] != "published" or ev["starts_at"] <= now_str():
        return
    link = url_for("public.event_detail", event_id=event_id)
    for fid in friend_ids(volunteer_id):
        friend = _vol(fid)
        if not friend or friend["deleted_at"] or not friend["notify_friend_plans"]:
            continue
        if scalar("SELECT 1 FROM registrations WHERE volunteer_id=? AND event_id=? AND status IN ('pending','approved')",
                  (fid, event_id)):
            continue
        if scalar("SELECT 1 FROM notifications WHERE user_id=? AND kind='n_friend_going' AND link=?",
                  (friend["user_id"], link)):
            continue
        if S.eligibility(friend, ev):
            continue
        notify(friend["user_id"], "n_friend_going", link, name=me["full_name"].split()[0], event=ev["title"])


def on_hours(volunteer_id, before, after):
    me = _vol(volunteer_id)
    if not me:
        return
    for m in FRIEND_MILESTONES:
        if before < m <= after:
            for fid in friend_ids(volunteer_id):
                friend = _vol(fid)
                if friend and not friend["deleted_at"] and friend["notify_friend_achievements"]:
                    notify(friend["user_id"], "n_friend_milestone", url_for("volunteer.friends"),
                           name=me["full_name"].split()[0], n=m, vid=volunteer_id)


def on_event_completed(event_id):
    ev = S.get_event(event_id)
    people = query("""SELECT v.* FROM registrations r JOIN volunteers v USING (volunteer_id)
                      WHERE r.event_id=? AND r.status='attended'""", (event_id,))
    for p in people:
        others = [o for o in people if o["volunteer_id"] != p["volunteer_id"]
                  and relation(p["volunteer_id"], o["volunteer_id"])["state"] is None]
        if not others:
            continue
        names = [o["full_name"].split()[0] for o in others[:2]]
        more = len(others) - len(names)
        notify(p["user_id"], "n_friend_met_more" if more else "n_friend_met", url_for("volunteer.friends", tab="met"),
               event=ev["title"], names=", ".join(names), more=more)


def give_kudos(me, to_vid, milestone):
    if milestone not in FRIEND_MILESTONES or not are_friends(me["volunteer_id"], to_vid):
        raise S.RuleError("rule_not_found")
    if S.total_hours(to_vid) < milestone:
        raise S.RuleError("rule_not_found")
    if scalar("SELECT 1 FROM kudos WHERE from_id=? AND to_id=? AND milestone=?", (me["volunteer_id"], to_vid, milestone)):
        raise S.RuleError("rule_kudos_given")
    friend = _vol(to_vid)
    with transaction():
        execute("INSERT INTO kudos (from_id, to_id, milestone) VALUES (?,?,?)", (me["volunteer_id"], to_vid, milestone))
        notify(friend["user_id"], "n_kudos", url_for("public.volunteer_profile", volunteer_id=me["volunteer_id"]),
               name=me["full_name"].split()[0], n=milestone)


def kudos_given(vid):
    return {(r["to_id"], r["milestone"]) for r in query("SELECT to_id, milestone FROM kudos WHERE from_id=?", (vid,))}


def recent_achievements(me, days=45):
    rows = query("""SELECT * FROM notifications WHERE user_id=? AND kind='n_friend_milestone'
                    AND created_at >= datetime('now','localtime', ?) ORDER BY created_at DESC LIMIT 6""",
                 (me["user_id"], f"-{days} days"))
    out = []
    for n in rows:
        p = json.loads(n["params"] or "{}")
        if p.get("vid") and are_friends(me["volunteer_id"], p["vid"]):
            v = _vol(p["vid"])
            out.append(dict(vid=p["vid"], n=p.get("n"), name=v["full_name"], avatar_path=v["avatar_path"],
                            at=n["created_at"]))
    return out
