from datetime import date, datetime

from .core import now_str
from .db import query, scalar

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _add_months(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def parse_period(kind, value):
    today = date.today()
    if kind == "month":
        try:
            start = datetime.strptime(value or "", "%Y-%m").date().replace(day=1)
        except ValueError:
            start = today.replace(day=1)
        if start > today:
            start = today.replace(day=1)
        return dict(kind="month", start=start, end=_add_months(start, 1), prev_start=_add_months(start, -1),
                    prev_end=start, value=start.strftime("%Y-%m"))
    try:
        year = int(value)
    except (TypeError, ValueError):
        year = today.year
    year = min(max(year, 2000), today.year)
    return dict(kind="year", start=date(year, 1, 1), end=date(year + 1, 1, 1), prev_start=date(year - 1, 1, 1),
                prev_end=date(year, 1, 1), value=str(year))


EVENTS_IN = """FROM events e WHERE e.event_id IN (SELECT event_id FROM org_events WHERE org_id=?) AND e.status IN ('published','completed') AND e.deleted_at IS NULL
               AND e.starts_at >= ? AND e.starts_at < ? AND e.starts_at <= ?"""


def _bounds(org_id, start, end):
    return (org_id, start.isoformat(), end.isoformat(), now_str())


def totals(org_id, start, end):
    args = _bounds(org_id, start, end)
    row = query(f"""SELECT COUNT(DISTINCT e.event_id) AS events,
        COUNT(DISTINCT CASE WHEN r.status='attended' THEN r.volunteer_id END) AS volunteers,
        COALESCE(SUM(CASE WHEN r.status='attended' THEN r.hours_confirmed END), 0) AS hours,
        COALESCE(SUM(r.status='attended'), 0) AS attended, COALESCE(SUM(r.status='no_show'), 0) AS no_show,
        COUNT(r.registration_id) AS applications
        FROM events e LEFT JOIN registrations r ON r.event_id = e.event_id
        WHERE e.event_id IN (SELECT e.event_id {EVENTS_IN})""", args, one=True)
    rating = query(f"""SELECT ROUND(AVG(f.rating), 1) AS avg, COUNT(*) AS n FROM feedback f
        JOIN registrations r USING (registration_id) WHERE f.status='published'
        AND r.event_id IN (SELECT e.event_id {EVENTS_IN})""", args, one=True)
    new = scalar(f"""SELECT COUNT(*) FROM (SELECT r.volunteer_id, MIN(e.starts_at) AS first FROM registrations r
        JOIN events e USING (event_id) WHERE e.event_id IN (SELECT event_id FROM org_events WHERE org_id=?)
        AND r.status='attended' GROUP BY r.volunteer_id)
        WHERE first >= ? AND first < ?""", (org_id, start.isoformat(), end.isoformat()))
    marked = row["attended"] + row["no_show"]
    return dict(events=row["events"], volunteers=row["volunteers"], hours=row["hours"], attended=row["attended"],
                no_show=row["no_show"], applications=row["applications"], new_volunteers=new,
                attendance=round(row["attended"] * 100 / marked) if marked else None,
                rating=rating["avg"], rating_n=rating["n"])


def change(cur, prev):
    if cur is None or prev is None:
        return None
    if not prev:
        return "new" if cur else None
    return round((cur - prev) * 100 / prev)


def hours_by_month(org_id, period):
    if period["kind"] == "year":
        first, count = period["start"], 12
    else:
        first, count = _add_months(period["start"], -5), 6
    out = []
    for i in range(count):
        a = _add_months(first, i)
        b = _add_months(a, 1)
        h = scalar(f"""SELECT COALESCE(SUM(r.hours_confirmed), 0) FROM registrations r
            WHERE r.status='attended' AND r.event_id IN (SELECT e.event_id {EVENTS_IN})""", _bounds(org_id, a, b))
        out.append(dict(label=MONTHS[a.month - 1], year=a.year, month=a.month, hours=h,
                        current=period["kind"] == "month" and a == period["start"]))
    return out


def by_direction(org_id, start, end):
    return query(f"""SELECT d.slug, d.name_en, d.name_ru, d.name_kk, d.icon,
        COALESCE(SUM(CASE WHEN r.status='attended' THEN r.hours_confirmed END), 0) AS hours,
        COUNT(DISTINCT e.event_id) AS events
        FROM events e JOIN directions d USING (direction_id) LEFT JOIN registrations r ON r.event_id = e.event_id
        WHERE e.event_id IN (SELECT e.event_id {EVENTS_IN}) GROUP BY d.direction_id HAVING hours > 0
        ORDER BY hours DESC""", _bounds(org_id, start, end))


def best_events(org_id, start, end, limit=5):
    return query(f"""SELECT e.event_id, e.title, e.starts_at,
        SUM(r.status='attended') AS attended, SUM(r.status='no_show') AS no_show,
        COALESCE(SUM(CASE WHEN r.status='attended' THEN r.hours_confirmed END), 0) AS hours,
        (SELECT ROUND(AVG(f.rating), 1) FROM feedback f JOIN registrations r2 USING (registration_id)
          WHERE r2.event_id = e.event_id AND f.status='published') AS rating
        FROM events e LEFT JOIN registrations r ON r.event_id = e.event_id
        WHERE e.event_id IN (SELECT e.event_id {EVENTS_IN}) GROUP BY e.event_id
        HAVING hours > 0 ORDER BY hours DESC, attended DESC LIMIT ?""", _bounds(org_id, start, end) + (limit,))


def top_volunteers(org_id, start, end, limit=5):
    rows = query(f"""SELECT v.volunteer_id, v.full_name, v.is_public, COUNT(*) AS events,
        SUM(r.hours_confirmed) AS hours FROM registrations r JOIN volunteers v USING (volunteer_id)
        JOIN users u ON u.user_id = v.user_id
        WHERE r.status='attended' AND u.deleted_at IS NULL AND r.event_id IN (SELECT e.event_id {EVENTS_IN})
        GROUP BY v.volunteer_id ORDER BY hours DESC, events DESC, v.full_name LIMIT ?""",
                 _bounds(org_id, start, end) + (limit,))
    out = []
    for r in rows:
        parts = r["full_name"].split()
        name = r["full_name"] if r["is_public"] else (parts[0] + (" " + parts[-1][0] + "." if len(parts) > 1 else ""))
        out.append(dict(r, display=name))
    return out


def years(org_id):
    first = scalar("""SELECT MIN(starts_at) FROM events WHERE status IN ('published','completed')
                       AND event_id IN (SELECT event_id FROM org_events WHERE org_id=?)""", (org_id,))
    this = date.today().year
    start = int(first[:4]) if first else this
    return list(range(this, start - 1, -1))


def months(org_id):
    first = scalar("""SELECT MIN(starts_at) FROM events WHERE status IN ('published','completed')
                       AND event_id IN (SELECT event_id FROM org_events WHERE org_id=?)""", (org_id,))
    today = date.today().replace(day=1)
    start = datetime.strptime(first[:7], "%Y-%m").date() if first else today
    out, cur = [], today
    while cur >= start and len(out) < 36:
        out.append(cur)
        cur = _add_months(cur, -1)
    return out


def build(org_id, kind, value):
    p = parse_period(kind, value)
    cur = totals(org_id, p["start"], p["end"])
    prev = totals(org_id, p["prev_start"], p["prev_end"])
    deltas = {k: change(cur[k], prev[k]) for k in ("events", "volunteers", "hours", "new_volunteers", "applications")}
    deltas["attendance"] = (cur["attendance"] - prev["attendance"]) if cur["attendance"] is not None \
        and prev["attendance"] is not None else None
    deltas["rating"] = round(cur["rating"] - prev["rating"], 1) if cur["rating"] and prev["rating"] else None
    monthly = hours_by_month(org_id, p)
    dirs = by_direction(org_id, p["start"], p["end"])
    return dict(period=p, cur=cur, prev=prev, deltas=deltas, monthly=monthly,
                monthly_max=max([m["hours"] for m in monthly] + [1]), dirs=dirs,
                dirs_max=max([d["hours"] for d in dirs] + [1]), best=best_events(org_id, p["start"], p["end"]),
                top=top_volunteers(org_id, p["start"], p["end"]), years=years(org_id), months=months(org_id),
                generated=now_str())
