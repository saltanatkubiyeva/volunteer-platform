import json
import time
from datetime import date

from flask import (Blueprint, flash, g, make_response, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from . import resets as R
from . import services as S
from .core import (_, audit, csrf_token, fmt_dt, form_int, login_required, notify,
                   now_str, safe_next)
from .db import execute, query, scalar, transaction
from .forms import (Errors, age_from, clean, normalize_phone, parse_date,
                    password_problem, valid_email)

bp = Blueprint("auth", __name__)

_FAILED = {}
MAX_ATTEMPTS, LOCK_SECONDS = 5, 300
ORG_TYPES = ("ngo", "foundation", "initiative", "university", "government", "business")


def _ref_data():
    return dict(cities=query("SELECT * FROM cities ORDER BY name_en"),
                directions=query("SELECT * FROM directions ORDER BY direction_id"))


def _start_session(user):
    session.clear()
    session.permanent = True
    session["uid"] = user["user_id"]
    session["lang"] = user["preferred_lang"]
    csrf_token()
    execute("UPDATE users SET last_login_at = ? WHERE user_id = ?", (now_str(), user["user_id"]))


def home_for(user):
    return {"admin": url_for("admin.dashboard"), "coordinator": url_for("org.dashboard")}.get(
        user["role"], url_for("volunteer.dashboard"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(home_for(g.user))
    email = ""
    if request.method == "POST":
        email = clean(request.form.get("email"), 120).lower()
        password = request.form.get("password", "")
        key = f"{email}|{request.remote_addr}"
        fails, since = _FAILED.get(key, (0, 0))
        if fails >= MAX_ATTEMPTS and time.time() - since < LOCK_SECONDS:
            flash(_("err_too_many_attempts"), "error")
            return render_template("auth/login.html", email=email), 429
        user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
        if not user or not check_password_hash(user["password_hash"], password):
            _FAILED[key] = (fails + 1, time.time())
            flash(_("err_wrong_credentials"), "error")
        elif not user["is_active"]:
            flash(_("err_account_blocked"), "error")
        else:
            _FAILED.pop(key, None)
            _start_session(user)
            flash(_("flash_welcome_back"), "success")
            return redirect(safe_next(request.args.get("next")) or home_for(user))
    return render_template("auth/login.html", email=email)


@bp.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    if g.user:
        return redirect(url_for("auth.settings"))
    email, sent_to = "", None
    if request.method == "POST":
        email = clean(request.form.get("email"), 120).lower()
        if not valid_email(email):
            flash(_("err_email"), "error")
        else:
            result = R.request_reset(email)
            if result == "sent":
                sent_to = R.mask_email(email)
            else:
                flash(_({"unknown": "err_reset_unknown", "blocked": "err_account_blocked",
                         "limited": "err_reset_limited"}[result]), "error")
    return render_template("auth/forgot.html", email=email, sent_to=sent_to)


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    row = R.find_valid(token)
    if not row:
        return render_template("auth/reset.html", invalid=True, errors=Errors()), 410
    errors = Errors()
    if request.method == "POST":
        pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
        problem = password_problem(pw)
        if problem:
            errors.add("password", problem)
        elif pw != pw2:
            errors.add("password2", "err_password_match")
        if not errors and R.complete_reset(token, generate_password_hash(pw)):
            for key in [k for k in _FAILED if k.startswith(row["email"] + "|")]:
                _FAILED.pop(key, None)
            flash(_("flash_password_reset_done"), "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", invalid=False, errors=errors, email=R.mask_email(row["email"]))


@bp.route("/logout", methods=["POST"])
def logout():
    lang = session.get("lang")
    session.clear()
    if lang:
        session["lang"] = lang
    flash(_("flash_logged_out"), "info")
    return redirect(url_for("public.home"))


@bp.route("/register")
def register():
    if g.user:
        return redirect(home_for(g.user))
    return render_template("auth/register_choice.html")


@bp.route("/register/volunteer", methods=["GET", "POST"])
def register_volunteer():
    if g.user:
        return redirect(home_for(g.user))
    f, errors = {}, Errors()
    if request.method == "POST":
        f = {k: clean(request.form.get(k), 300) for k in
             ("full_name", "email", "phone", "birth_date", "city_id")}
        f["email"] = f["email"].lower()
        f["directions"] = [int(x) for x in request.form.getlist("directions") if x.isdigit()]
        pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")

        if len(f["full_name"]) < 3:
            errors.add("full_name", "err_name")
        if not valid_email(f["email"]):
            errors.add("email", "err_email")
        elif scalar("SELECT 1 FROM users WHERE email = ?", (f["email"],)):
            errors.add("email", "err_email_taken")
        phone = normalize_phone(f["phone"])
        if not phone:
            errors.add("phone", "err_phone")
        birth = parse_date(f["birth_date"])
        if not birth:
            errors.add("birth_date", "err_date")
        elif age_from(birth) < 14:
            errors.add("birth_date", "err_age_14")
        elif age_from(birth) > 100:
            errors.add("birth_date", "err_date")
        city_id = form_int("city_id")
        if not city_id or not scalar("SELECT 1 FROM cities WHERE city_id = ?", (city_id,)):
            errors.add("city_id", "err_city")
        if not f["directions"]:
            errors.add("directions", "err_directions")
        problem = password_problem(pw)
        if problem:
            errors.add("password", problem)
        elif pw != pw2:
            errors.add("password2", "err_password_match")
        if not request.form.get("agree"):
            errors.add("agree", "err_agree")

        if not errors:
            with transaction():
                uid = execute("INSERT INTO users (email, password_hash, role, preferred_lang)"
                              " VALUES (?,?,?,?)",
                              (f["email"], generate_password_hash(pw), "volunteer", g.lang))
                vid = execute("INSERT INTO volunteers (user_id, full_name, phone, birth_date, city_id)"
                              " VALUES (?,?,?,?,?)",
                              (uid, f["full_name"], phone, birth.isoformat(), city_id))
                for d in set(f["directions"]):
                    if scalar("SELECT 1 FROM directions WHERE direction_id = ?", (d,)):
                        execute("INSERT INTO volunteer_directions VALUES (?,?)", (vid, d))
                notify(uid, "n_welcome_volunteer", url_for("volunteer.profile_edit"))
            _start_session(query("SELECT * FROM users WHERE user_id = ?", (uid,), one=True))
            if age_from(birth) < 18:
                flash(_("flash_registered_minor"), "info")
                return redirect(url_for("volunteer.consent"))
            flash(_("flash_registered"), "success")
            return redirect(url_for("volunteer.dashboard"))
    return render_template("auth/register_volunteer.html", f=f, errors=errors, **_ref_data())


@bp.route("/register/organization", methods=["GET", "POST"])
def register_organization():
    if g.user:
        return redirect(home_for(g.user))
    f, errors = {}, Errors()
    if request.method == "POST":
        keys = ("name", "bin", "org_type", "city_id", "address", "org_email", "org_phone",
                "website", "description", "full_name", "position", "phone", "email")
        f = {k: clean(request.form.get(k), 2000 if k == "description" else 200) for k in keys}
        f["email"], f["org_email"] = f["email"].lower(), f["org_email"].lower()
        f["directions"] = [int(x) for x in request.form.getlist("directions") if x.isdigit()]
        pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")

        if len(f["name"]) < 3:
            errors.add("name", "err_required")
        elif scalar("SELECT 1 FROM organizations WHERE name = ?", (f["name"],)):
            errors.add("name", "err_org_name_taken")
        if not (f["bin"].isdigit() and len(f["bin"]) == 12):
            errors.add("bin", "err_bin")
        elif scalar("SELECT 1 FROM organizations WHERE bin = ?", (f["bin"],)):
            errors.add("bin", "err_bin_taken")
        if f["org_type"] not in ORG_TYPES:
            errors.add("org_type", "err_required")
        city_id = form_int("city_id")
        if not city_id or not scalar("SELECT 1 FROM cities WHERE city_id = ?", (city_id,)):
            errors.add("city_id", "err_city")
        if len(f["address"]) < 5:
            errors.add("address", "err_required")
        if not valid_email(f["org_email"]):
            errors.add("org_email", "err_email")
        org_phone = normalize_phone(f["org_phone"])
        if not org_phone:
            errors.add("org_phone", "err_phone")
        if f["website"] and not f["website"].startswith(("http://", "https://")):
            f["website"] = "https://" + f["website"]
        if len(f["description"]) < 40:
            errors.add("description", "err_description_short")
        if not f["directions"]:
            errors.add("directions", "err_directions")
        if len(f["full_name"]) < 3:
            errors.add("full_name", "err_name")
        phone = normalize_phone(f["phone"])
        if not phone:
            errors.add("phone", "err_phone")
        if not valid_email(f["email"]):
            errors.add("email", "err_email")
        elif scalar("SELECT 1 FROM users WHERE email = ?", (f["email"],)):
            errors.add("email", "err_email_taken")
        problem = password_problem(pw)
        if problem:
            errors.add("password", problem)
        elif pw != pw2:
            errors.add("password2", "err_password_match")
        if not request.form.get("agree"):
            errors.add("agree", "err_agree")

        if not errors:
            with transaction():
                oid = execute(
                    "INSERT INTO organizations (name, bin, org_type, description, city_id, address,"
                    " email, phone, website) VALUES (?,?,?,?,?,?,?,?,?)",
                    (f["name"], f["bin"], f["org_type"], f["description"], city_id, f["address"],
                     f["org_email"], org_phone, f["website"] or None))
                for d in set(f["directions"]):
                    if scalar("SELECT 1 FROM directions WHERE direction_id = ?", (d,)):
                        execute("INSERT INTO organization_directions VALUES (?,?)", (oid, d))
                uid = execute("INSERT INTO users (email, password_hash, role, preferred_lang)"
                              " VALUES (?,?,?,?)",
                              (f["email"], generate_password_hash(pw), "coordinator", g.lang))
                execute("INSERT INTO coordinators (user_id, org_id, full_name, phone, position, is_owner)"
                        " VALUES (?,?,?,?,?,1)", (uid, oid, f["full_name"], phone, f["position"] or None))
                for admin in query("SELECT user_id FROM users WHERE role='admin' AND is_active=1"):
                    notify(admin["user_id"], "n_admin_new_org", url_for("admin.org_review", org_id=oid),
                           org=f["name"])
            _start_session(query("SELECT * FROM users WHERE user_id = ?", (uid,), one=True))
            flash(_("flash_org_registered"), "success")
            return redirect(url_for("org.dashboard"))
    return render_template("auth/register_org.html", f=f, errors=errors, org_types=ORG_TYPES,
                           **_ref_data())


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    errors = Errors()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "language":
            lang = request.form.get("preferred_lang")
            if lang in ("en", "ru", "kk"):
                execute("UPDATE users SET preferred_lang=? WHERE user_id=?", (lang, g.user["user_id"]))
                session["lang"] = lang
                g.lang = lang
                flash(_("flash_saved"), "success")
                return redirect(url_for("auth.settings"))
        elif action == "subscriptions" and g.volunteer:
            def ids(name):
                return [int(x) for x in request.form.getlist(name) if x.isdigit()]
            S.save_subscriptions(g.volunteer["volunteer_id"], ids("cities"), ids("directions"))
            flash(_("flash_subscriptions_saved"), "success")
            return redirect(url_for("auth.settings") + "#subscriptions")
        elif action == "password":
            current = request.form.get("current", "")
            pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
            if not check_password_hash(g.user["password_hash"], current):
                errors.add("current", "err_current_password")
            problem = password_problem(pw)
            if problem:
                errors.add("password", problem)
            elif pw != pw2:
                errors.add("password2", "err_password_match")
            if not errors:
                execute("UPDATE users SET password_hash=? WHERE user_id=?",
                        (generate_password_hash(pw), g.user["user_id"]))
                audit("password_changed", "users", g.user["user_id"])
                flash(_("flash_password_changed"), "success")
                return redirect(url_for("auth.settings"))
    subs = None
    if g.volunteer:
        subs = dict(zip(("cities", "directions"), S.subscriptions(g.volunteer["volunteer_id"])),
                    all_cities=query("SELECT * FROM cities ORDER BY name_en"),
                    all_directions=query("SELECT * FROM directions ORDER BY direction_id"))
    return render_template("auth/settings.html", errors=errors, subs=subs)


@bp.route("/notifications")
@login_required
def notifications():
    rows = query("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC, notification_id DESC LIMIT 100",
                 (g.user["user_id"],))
    return render_template("auth/notifications.html", rows=rows)


@bp.route("/notifications/read", methods=["POST"])
@login_required
def notifications_read():
    nid = form_int("id")
    if nid:
        row = query("SELECT link FROM notifications WHERE notification_id=? AND user_id=?",
                    (nid, g.user["user_id"]), one=True)
        execute("UPDATE notifications SET is_read=1 WHERE notification_id=? AND user_id=?", (nid, g.user["user_id"]))
        if row and row["link"] and safe_next(row["link"]):
            return redirect(row["link"])
    else:
        execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (g.user["user_id"],))
    return redirect(url_for("auth.notifications"))
