from datetime import datetime, timedelta

from . import services as S
from .core import audit, now_str
from .db import execute, query, transaction

MAX_REPEAT = 12
FMT = "%Y-%m-%d %H:%M"

COPY_COLUMNS = ("org_id", "coordinator_id", "direction_id", "city_id", "title", "summary", "description", "address",
                "max_volunteers", "min_age", "requires_approval", "requirements", "provided", "cover_path", "lat", "lng")


def _shift(value, delta):
    return (datetime.strptime(value, FMT) + delta).strftime(FMT)


def copy_event(src, start, status, series_id=None):
    delta = start - datetime.strptime(src["starts_at"], FMT)
    deadline = datetime.strptime(src["registration_deadline"], FMT) + delta
    if deadline <= datetime.now():
        deadline = max(datetime.now(), start - timedelta(hours=1))
    values = [src[c] for c in COPY_COLUMNS] + [start.strftime(FMT), _shift(src["ends_at"], delta),
                                                deadline.strftime(FMT), status, series_id]
    cols = COPY_COLUMNS + ("starts_at", "ends_at", "registration_deadline", "status", "series_id")
    new_id = execute(f"INSERT INTO events ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", values)
    for sh in S.event_shifts(src["event_id"]):
        execute("""INSERT INTO event_shifts (event_id, title, starts_at, ends_at, max_volunteers, position)
                   VALUES (?,?,?,?,?,?)""", (new_id, sh["title"], _shift(sh["starts_at"], delta),
                                              _shift(sh["ends_at"], delta), sh["max_volunteers"], sh["position"]))
    for r in S.event_requirements(src["event_id"]):
        execute("INSERT INTO event_requirements (event_id, skill_id) VALUES (?,?)", (new_id, r["skill_id"]))
    return new_id


def check_start(start):
    if not start:
        raise S.RuleError("err_date")
    if start <= datetime.now():
        raise S.RuleError("err_start_future")


def duplicate(coordinator, src, start):
    check_start(start)
    with transaction():
        new_id = copy_event(src, start, "draft")
        audit("event_duplicated", "events", new_id, src["event_id"], "draft")
    return new_id


def repeat_weekly(coordinator, org, src, start, count):
    check_start(start)
    if not 2 <= count <= MAX_REPEAT:
        raise S.RuleError("err_repeat_count", n=MAX_REPEAT)
    status = "published" if org["status"] == "verified" else "draft"
    series_id = src["series_id"] or src["event_id"]
    with transaction():
        if not src["series_id"]:
            execute("UPDATE events SET series_id=? WHERE event_id=?", (series_id, src["event_id"]))
        ids = [copy_event(src, start + timedelta(weeks=k), status, series_id) for k in range(count)]
        audit("event_series_created", "events", series_id, src["event_id"], f"{count} weekly")
        if status == "published":
            S.notify_subscribers(ids[0])
    return ids


def series_events(series_id):
    if not series_id:
        return []
    return query(S.EVENT_SELECT + " WHERE e.series_id=? AND e.deleted_at IS NULL ORDER BY e.starts_at", (series_id,))


def cancel_series(user_id, org_id, series_id, reason):
    now = now_str()
    rows = query("""SELECT event_id FROM events WHERE series_id=? AND org_id=? AND deleted_at IS NULL AND status IN ('published','draft')
                    AND starts_at > ? ORDER BY starts_at""", (series_id, org_id, now))
    if not rows:
        raise S.RuleError("rule_series_nothing")
    for r in rows:
        S.cancel_event(user_id, r["event_id"], reason)
    return len(rows)
