import calendar
from datetime import date, timedelta

MONTH_NAMES = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
    "ru": ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь",
           "Ноябрь", "Декабрь"],
    "kk": ["Қаңтар", "Ақпан", "Наурыз", "Сәуір", "Мамыр", "Маусым", "Шілде", "Тамыз", "Қыркүйек", "Қазан",
           "Қараша", "Желтоқсан"],
}


def parse_month(value, fallback):
    try:
        y, m = (int(x) for x in (value or "").split("-"))
        if 2000 <= y <= 2100 and 1 <= m <= 12:
            return date(y, m, 1)
    except ValueError:
        pass
    return fallback.replace(day=1)


def month_grid(first):
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month)
    prev_month = (first - timedelta(days=1)).replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    return weeks, prev_month, next_month


def group_by_day(rows):
    days = {}
    for ev in rows:
        days.setdefault(ev["starts_at"][:10], []).append(ev)
    return days


def map_points(rows, loc, fmt_date, fmt_time, url_for):
    points = []
    for ev in rows:
        if ev["lat"] is None:
            continue
        left = ev["max_volunteers"] - ev["taken"]
        points.append(dict(
            id=ev["event_id"], city_id=ev["city_id"], lat=ev["lat"], lng=ev["lng"], title=ev["title"],
            when=f"{fmt_date(ev['starts_at'], True, False)} · {fmt_time(ev['starts_at'])}",
            org=ev["org_name"], city=loc(ev, "city_name"), address=ev["address"], dir=loc(ev, "dir_name"),
            tone=ev["dir_tone"], color="#c8f04a",
            left=left, taken=ev["taken"], urgent=bool(ev["is_urgent"]) and left > 0,
            url=url_for("public.event_detail", event_id=ev["event_id"]),
        ))
    return points
