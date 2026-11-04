"""DEMEU — volunteer platform for Kazakhstan (Flask application factory)."""
import os
import secrets
from datetime import timedelta

from flask import Flask, g, render_template, request, session

from . import core
from .db import close_db
from .icons import icon, logo_mark
from . import photos

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _secret_key(instance_dir):
    path = os.path.join(instance_dir, "secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


def create_app(test_config=None):
    instance_dir = os.path.join(BASE_DIR, "instance")
    os.makedirs(os.path.join(instance_dir, "uploads"), exist_ok=True)

    app = Flask(__name__, instance_path=instance_dir)
    app.config.update(
        SECRET_KEY=_secret_key(instance_dir),
        DATABASE=os.path.join(instance_dir, "demeu.db"),
        UPLOAD_DIR=os.path.join(instance_dir, "uploads"),
        MAX_UPLOAD_MB=5,
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    )
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(close_db)

    @app.before_request
    def before():
        g.lang = core.get_lang()
        core.load_user()
        core.check_csrf()

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return resp

    # helpers available everywhere, including imported macros
    app.jinja_env.globals.update(
        _=core._, loc=core.loc, fmt_date=core.fmt_date, fmt_time=core.fmt_time,
        fmt_dt=core.fmt_dt, fmt_hours=core.fmt_hours, initials=core.initials,
        csrf_field=core.csrf_field, csrf_token=core.csrf_token, icon=icon, logo_mark=logo_mark,
        LANGS=core.LANGS, LANG_LABELS=core.LANG_LABELS, event_phase=core.event_phase,
        age_on=core.age_on, duration_hours=core.duration_hours,
        notification_text=core.notification_text,
        direction_photo=photos.direction_photo, photo_url=photos.photo_url,
        fallback_url=photos.fallback_url, HERO_PHOTO=photos.HERO, CITY_PHOTO=photos.CITY,
    )

    @app.context_processor
    def inject():
        return dict(lang=g.get("lang", "en"), unread=core.unread_count())

    app.jinja_env.filters["nl2br"] = core.nl2br
    app.jinja_env.filters["phone"] = core.fmt_phone

    from . import auth, public, volunteer, org, admin, media
    app.register_blueprint(public.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(volunteer.bp)
    app.register_blueprint(org.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(media.bp)

    def error_page(code):
        def handler(err):
            return render_template("error.html", code=code,
                                   description=getattr(err, "description", "")), code
        return handler

    for code in (400, 403, 404, 413, 500):
        app.register_error_handler(code, error_page(code))

    return app
