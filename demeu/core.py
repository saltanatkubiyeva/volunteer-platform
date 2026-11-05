import json
import math
import os
import secrets
import uuid
from datetime import date, datetime
from functools import wraps

from flask import (abort, current_app, flash, g, redirect, request, session,
                   url_for)
from markupsafe import Markup, escape

from .db import execute, query, scalar
from .translations import TRANSLATIONS

LANGS = ("en", "ru", "kk")
LANG_LABELS = {"en": "EN", "ru": "RU", "kk": "KZ"}
DT_FMT = "%Y-%m-%d %H:%M"

MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "ru": ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"],
    "kk": ["қаң", "ақп", "нау", "сәу", "мам", "мау", "шіл", "там", "қыр", "қаз", "қар", "жел"],
}
WEEKDAYS = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "ru": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
    "kk": ["Дс", "Сс", "Ср", "Бс", "Жм", "Сб", "Жс"],
}


def get_lang():
    lang = session.get("lang")
    if lang in LANGS:
        return lang
    best = request.accept_languages.best_match(["en", "ru", "kk"]) if request else None
    return best or "en"


def _(key, **params):
    entry = TRANSLATIONS.get(key)
    if entry is None:
        text = key
    else:
        lang = g.get("lang", "en")
        text = entry.get(lang) or entry.get("en") or key
    if params:
        try:
            text = text.format(**params)
        except (KeyError, IndexError):
            pass
    return text


def loc(row, field):
    if row is None:
        return ""
    lang = g.get("lang", "en")
    keys = row.keys() if hasattr(row, "keys") else row
    for k in (f"{field}_{lang}", f"{field}_en", field):
        if k in keys and row[k]:
            return row[k]
    return ""


def parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in (DT_FMT, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def fmt_date(value, with_weekday=False, with_year=True):
    d = parse_dt(value)
    if not d:
        return ""
    lang = g.get("lang", "en")
    s = f"{d.day} {MONTHS[lang][d.month - 1]}"
    if with_year:
        s += f" {d.year}"
    if with_weekday:
        s = f"{WEEKDAYS[lang][d.weekday()]}, " + s
    return s


def fmt_time(value):
    d = parse_dt(value)
    return d.strftime("%H:%M") if d else ""


def fmt_dt(value):
    d = parse_dt(value)
    return f"{fmt_date(d)}, {d:%H:%M}" if d else ""


def fmt_hours(value):
    if value is None:
        return "0"
    v = float(value)
    return str(int(v)) if v.is_integer() else f"{v:.1f}"


def age_on(birth_date, on=None):
    b = parse_dt(birth_date)
    if not b:
        return None
    on = on or date.today()
    if isinstance(on, datetime):
        on = on.date()
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


def now_str():
    return datetime.now().strftime(DT_FMT)


def fmt_phone(value):
    v = value or ""
    if len(v) == 12 and v.startswith("+7"):
        return f"+7 {v[2:5]} {v[5:8]} {v[8:10]} {v[10:12]}"
    return v


def initials(name):
    parts = [p for p in (name or "").split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def duration_hours(starts_at, ends_at):
    a, b = parse_dt(starts_at), parse_dt(ends_at)
    if not a or not b:
        return 0
    return round((b - a).total_seconds() / 3600, 1)


def event_phase(ev):
    if ev["status"] in ("cancelled", "draft"):
        return ev["status"]
    now = datetime.now()
    if parse_dt(ev["ends_at"]) <= now or ev["status"] == "completed":
        return "finished"
    if parse_dt(ev["starts_at"]) <= now:
        return "ongoing"
    return "upcoming"


def nl2br(text):
    if not text:
        return ""
    return Markup("<br>".join(escape(line) for line in str(text).splitlines()))


def load_user():
    g.user = g.volunteer = g.coordinator = g.org = None
    uid = session.get("uid")
    if not uid:
        return
    user = query("SELECT * FROM users WHERE user_id = ?", (uid,), one=True)
    if not user or not user["is_active"]:
        session.clear()
        return
    g.user = user
    if user["role"] == "volunteer":
        g.volunteer = query("SELECT * FROM volunteers WHERE user_id = ?", (uid,), one=True)
    elif user["role"] == "coordinator":
        g.coordinator = query("SELECT * FROM coordinators WHERE user_id = ?", (uid,), one=True)
        if g.coordinator:
            g.org = query("SELECT * FROM organizations WHERE org_id = ?",
                          (g.coordinator["org_id"],), one=True)


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            flash(_("flash_login_required"), "info")
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*a, **kw)
    return wrapped


def role_required(*roles):
    def deco(view):
        @wraps(view)
        def wrapped(*a, **kw):
            if g.user is None:
                flash(_("flash_login_required"), "info")
                return redirect(url_for("auth.login", next=request.full_path))
            if g.user["role"] not in roles:
                abort(403)
            if g.user["role"] == "volunteer" and not g.volunteer:
                abort(403)
            if g.user["role"] == "coordinator" and not g.coordinator:
                abort(403)
            return view(*a, **kw)
        return wrapped
    return deco


def csrf_token():
    tok = session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["csrf"] = tok
    return tok


def csrf_field():
    return Markup(f'<input type="hidden" name="csrf_token" value="{csrf_token()}">')


def check_csrf():
    if request.method == "POST" and not current_app.config.get("TESTING_NO_CSRF"):
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400, description="CSRF token missing or invalid")


IMAGE_EXT = {"png", "jpg", "jpeg", "webp"}
DOC_EXT = {"pdf", "png", "jpg", "jpeg"}


def save_upload(file, allowed, subdir):
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in allowed:
        raise ValueError("err_file_type")
    head = file.stream.read(12)
    file.stream.seek(0)
    signatures = {
        "png": [b"\x89PNG"], "jpg": [b"\xff\xd8\xff"], "jpeg": [b"\xff\xd8\xff"],
        "pdf": [b"%PDF"], "webp": [b"RIFF"],
    }
    if not any(head.startswith(sig) for sig in signatures.get(ext, [])):
        raise ValueError("err_file_type")
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > current_app.config["MAX_UPLOAD_MB"] * 1024 * 1024:
        raise ValueError("err_file_size")
    folder = os.path.join(current_app.config["UPLOAD_DIR"], subdir)
    os.makedirs(folder, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(folder, name))
    return f"{subdir}/{name}"


def notify(user_id, kind, link=None, **params):
    execute("INSERT INTO notifications (user_id, kind, params, link) VALUES (?,?,?,?)",
            (user_id, kind, json.dumps(params, ensure_ascii=False), link))


def notification_text(n):
    try:
        params = json.loads(n["params"] or "{}")
    except ValueError:
        params = {}
    return _(n["kind"], **params)


def audit(action, entity, entity_id=None, old=None, new=None):
    execute("INSERT INTO audit_log (user_id, action, entity, entity_id, old_value, new_value)"
            " VALUES (?,?,?,?,?,?)",
            (g.user["user_id"] if g.get("user") else None, action, entity, entity_id,
             None if old is None else str(old), None if new is None else str(new)))


def unread_count():
    if not g.get("user"):
        return 0
    return scalar("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                  (g.user["user_id"],))


class Page:
    def __init__(self, total, page, per_page):
        self.total = total
        self.per_page = per_page
        self.pages = max(1, math.ceil(total / per_page))
        self.page = min(max(1, page), self.pages)
        self.offset = (self.page - 1) * per_page

    def url(self, page):
        args = request.args.to_dict()
        args["page"] = page
        return url_for(request.endpoint, **{**(request.view_args or {}), **args})


def page_arg():
    try:
        return int(request.args.get("page", 1))
    except ValueError:
        return 1


def form_int(name, default=None):
    try:
        return int(request.form.get(name, ""))
    except ValueError:
        return default


def arg_int(name, default=None):
    try:
        return int(request.args.get(name, ""))
    except ValueError:
        return default


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None
