from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

from . import services as S
from .core import (IMAGE_EXT, DOC_EXT, _, age_on, audit, form_int, notify,
                   now_str, role_required, save_upload)
from .db import execute, query, scalar, transaction
from .forms import Errors, clean, normalize_phone

bp = Blueprint("volunteer", __name__, url_prefix="/me")
volunteer_only = role_required("volunteer")

REG_SELECT = """SELECT r.*, e.title, e.starts_at, e.ends_at, e.address, e.status AS ev_status, e.cancel_reason,
    e.event_id, e.cover_path, o.name AS org_name, o.org_id,
    d.slug AS dir_slug, d.name_en AS dir_name_en, d.name_ru AS dir_name_ru, d.name_kk AS dir_name_kk, d.icon AS dir_icon, d.tone AS dir_tone,
    c.name_en AS city_name_en, c.name_ru AS city_name_ru, c.name_kk AS city_name_kk,
    ce.code AS cert_code, f.rating AS my_rating
    FROM registrations r JOIN events e USING (event_id) JOIN organizations o ON o.org_id = e.org_id
    JOIN directions d ON d.direction_id = e.direction_id JOIN cities c ON c.city_id = e.city_id
    LEFT JOIN certificates ce ON ce.registration_id = r.registration_id
    LEFT JOIN feedback f ON f.registration_id = r.registration_id"""


@bp.route("/")
@volunteer_only
def dashboard():
    vid = g.volunteer["volunteer_id"]
    now = now_str()
    upcoming = query(REG_SELECT + """ WHERE r.volunteer_id=? AND r.status IN ('pending','approved')
                     AND e.ends_at >= ? AND e.status='published' ORDER BY e.starts_at""", (vid, now))
    to_review = query(REG_SELECT + " WHERE r.volunteer_id=? AND r.status='attended' AND f.rating IS NULL"
                      " ORDER BY e.starts_at DESC LIMIT 3", (vid,))
    recent = query(REG_SELECT + " WHERE r.volunteer_id=? AND r.status='attended' ORDER BY e.starts_at DESC LIMIT 5",
                   (vid,))
    my_dirs = [r["direction_id"] for r in query("SELECT direction_id FROM volunteer_directions WHERE volunteer_id=?", (vid,))]
    marks = ",".join("?" * len(my_dirs)) or "NULL"
    recommended = query(S.EVENT_SELECT + f""" WHERE {S.PUBLIC_WHERE} AND e.status='published'
        AND e.registration_deadline >= ? AND e.direction_id IN ({marks})
        AND NOT EXISTS (SELECT 1 FROM registrations r WHERE r.event_id=e.event_id AND r.volunteer_id=?)
        AND (SELECT COUNT(*) FROM registrations r WHERE r.event_id=e.event_id AND r.status IN ('approved','attended')) < e.max_volunteers
        ORDER BY (e.city_id = ?) DESC, e.starts_at LIMIT 3""",
                        [now] + my_dirs + [vid, g.volunteer["city_id"]])
    age = age_on(g.volunteer["birth_date"])
    notifications = query("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC, notification_id DESC LIMIT 5",
                          (g.user["user_id"],))
    profile_missing = [k for k in ("about", "skills", "avatar_path") if not g.volunteer[k]]
    return render_template("volunteer/dashboard.html", upcoming=upcoming, to_review=to_review, recent=recent,
                           recommended=recommended, stats=S.volunteer_stats(vid), age=age,
                           consent=S.consent_status(vid), notifications=notifications,
                           profile_missing=profile_missing)


@bp.route("/applications")
@volunteer_only
def applications():
    vid = g.volunteer["volunteer_id"]
    tab = request.args.get("tab", "active")
    now = now_str()
    conditions = {
        "active": ("r.status IN ('pending','approved') AND e.ends_at >= ? AND e.status <> 'cancelled'", [now], "e.starts_at"),
        "history": ("(r.status IN ('attended','no_show') OR (r.status='approved' AND e.ends_at < ?))", [now], "e.starts_at DESC"),
        "closed": ("(r.status IN ('rejected','cancelled') OR e.status='cancelled')", [], "r.applied_at DESC"),
    }
    cond, extra, order = conditions.get(tab, conditions["active"])
    rows = query(REG_SELECT + f" WHERE r.volunteer_id=? AND {cond} ORDER BY {order}", [vid] + extra)
    counts = {k: scalar(f"SELECT COUNT(*) FROM registrations r JOIN events e USING (event_id) WHERE r.volunteer_id=? AND {c}",
                        [vid] + x) for k, (c, x, _o) in conditions.items()}
    return render_template("volunteer/applications.html", rows=rows, tab=tab, counts=counts)


@bp.route("/apply/<int:event_id>", methods=["POST"])
@volunteer_only
def apply(event_id):
    motivation = clean(request.form.get("motivation"), 500)
    try:
        status = S.apply(g.volunteer, event_id, motivation)
        flash(_("flash_applied_pending" if status == "pending" else "flash_applied_approved"), "success")
    except S.RuleError as e:
        flash(_(e.key, **e.params), "error")
    return redirect(url_for("public.event_detail", event_id=event_id))


@bp.route("/applications/<int:registration_id>/cancel", methods=["POST"])
@volunteer_only
def cancel(registration_id):
    try:
        S.cancel_by_volunteer(g.volunteer, registration_id)
        flash(_("flash_application_cancelled"), "info")
    except S.RuleError as e:
        flash(_(e.key, **e.params), "error")
    return redirect(request.referrer or url_for("volunteer.applications"))


@bp.route("/applications/<int:registration_id>/feedback", methods=["POST"])
@volunteer_only
def feedback(registration_id):
    reg = query("SELECT * FROM registrations WHERE registration_id=? AND volunteer_id=?",
                (registration_id, g.volunteer["volunteer_id"]), one=True)
    rating = form_int("rating")
    if not reg or reg["status"] != "attended":
        flash(_("rule_feedback_attended"), "error")
    elif rating not in range(1, 6):
        flash(_("err_rating"), "error")
    elif scalar("SELECT 1 FROM feedback WHERE registration_id=?", (registration_id,)):
        flash(_("rule_feedback_once"), "error")
    else:
        execute("INSERT INTO feedback (registration_id, rating, comment) VALUES (?,?,?)",
                (registration_id, rating, clean(request.form.get("comment"), 600) or None))
        flash(_("flash_feedback_thanks"), "success")
    return redirect(request.referrer or url_for("volunteer.applications", tab="history"))


@bp.route("/certificates/<int:registration_id>", methods=["POST"])
@volunteer_only
def certificate_issue(registration_id):
    try:
        code = S.issue_certificate(g.volunteer, registration_id)
        return redirect(url_for("volunteer.certificate", code=code))
    except S.RuleError as e:
        flash(_(e.key), "error")
        return redirect(url_for("volunteer.applications", tab="history"))


@bp.route("/certificate/<code>")
@volunteer_only
def certificate(code):
    cert = query("""SELECT ce.*, r.hours_confirmed, r.volunteer_id, v.full_name, e.title, e.starts_at, e.ends_at,
        e.address, o.name AS org_name, co.full_name AS confirmed_name, co.position AS confirmed_position,
        c.name_en AS city_name_en, c.name_ru AS city_name_ru, c.name_kk AS city_name_kk
        FROM certificates ce JOIN registrations r USING (registration_id) JOIN volunteers v USING (volunteer_id)
        JOIN events e USING (event_id) JOIN organizations o ON o.org_id=e.org_id JOIN cities c ON c.city_id=e.city_id
        LEFT JOIN coordinators co ON co.coordinator_id=r.confirmed_by WHERE ce.code=?""", (code,), one=True)
    if not cert or cert["volunteer_id"] != g.volunteer["volunteer_id"]:
        abort(404)
    return render_template("volunteer/certificate.html", cert=cert)


@bp.route("/profile", methods=["GET", "POST"])
@volunteer_only
def profile_edit():
    v = g.volunteer
    errors = Errors()
    cities = query("SELECT * FROM cities ORDER BY name_en")
    directions = query("SELECT * FROM directions ORDER BY direction_id")
    selected = [r["direction_id"] for r in query("SELECT direction_id FROM volunteer_directions WHERE volunteer_id=?",
                                                  (v["volunteer_id"],))]
    f = dict(v)
    if request.method == "POST":
        f.update({k: clean(request.form.get(k), 1500 if k in ("about", "skills") else 120)
                  for k in ("full_name", "phone", "about", "skills")})
        f["city_id"] = form_int("city_id")
        f["is_public"] = 1 if request.form.get("is_public") else 0
        f["show_contacts"] = 1 if request.form.get("show_contacts") else 0
        selected = [int(x) for x in request.form.getlist("directions") if x.isdigit()]
        if len(f["full_name"]) < 3:
            errors.add("full_name", "err_name")
        phone = normalize_phone(f["phone"])
        if not phone:
            errors.add("phone", "err_phone")
        if not f["city_id"] or not scalar("SELECT 1 FROM cities WHERE city_id=?", (f["city_id"],)):
            errors.add("city_id", "err_city")
        if not selected:
            errors.add("directions", "err_directions")
        avatar = v["avatar_path"]
        try:
            new_avatar = save_upload(request.files.get("avatar"), IMAGE_EXT, "avatars")
            if new_avatar:
                avatar = new_avatar
        except ValueError as e:
            errors.add("avatar", str(e))
        if request.form.get("remove_avatar"):
            avatar = None
        if not errors:
            with transaction():
                execute("""UPDATE volunteers SET full_name=?, phone=?, city_id=?, about=?, skills=?, avatar_path=?,
                           is_public=?, show_contacts=? WHERE volunteer_id=?""",
                        (f["full_name"], phone, f["city_id"], f["about"] or None, f["skills"] or None, avatar,
                         f["is_public"], f["show_contacts"], v["volunteer_id"]))
                execute("DELETE FROM volunteer_directions WHERE volunteer_id=?", (v["volunteer_id"],))
                for d in set(selected):
                    if scalar("SELECT 1 FROM directions WHERE direction_id=?", (d,)):
                        execute("INSERT INTO volunteer_directions VALUES (?,?)", (v["volunteer_id"], d))
            flash(_("flash_profile_saved"), "success")
            return redirect(url_for("public.volunteer_profile", volunteer_id=v["volunteer_id"]))
    return render_template("volunteer/profile_edit.html", f=f, errors=errors, cities=cities,
                           directions=directions, selected=selected)


@bp.route("/consent", methods=["GET", "POST"])
@volunteer_only
def consent():
    v = g.volunteer
    age = age_on(v["birth_date"])
    history = query("SELECT * FROM consents WHERE volunteer_id=? ORDER BY consent_id DESC", (v["volunteer_id"],))
    current = history[0] if history else None
    errors, f = Errors(), {}
    if request.method == "POST":
        if age >= 18:
            abort(400)
        if current and current["status"] in ("pending", "approved"):
            flash(_("rule_consent_exists"), "error")
            return redirect(url_for("volunteer.consent"))
        f = {k: clean(request.form.get(k), 120) for k in ("parent_name", "parent_phone")}
        if len(f["parent_name"]) < 3:
            errors.add("parent_name", "err_name")
        phone = normalize_phone(f["parent_phone"])
        if not phone:
            errors.add("parent_phone", "err_phone")
        path = None
        try:
            path = save_upload(request.files.get("document"), DOC_EXT, "consents")
            if not path:
                errors.add("document", "err_file_required")
        except ValueError as e:
            errors.add("document", str(e))
        if not errors:
            cid = execute("INSERT INTO consents (volunteer_id, parent_name, parent_phone, file_path) VALUES (?,?,?,?)",
                          (v["volunteer_id"], f["parent_name"], phone, path))
            for admin in query("SELECT user_id FROM users WHERE role='admin' AND is_active=1"):
                notify(admin["user_id"], "n_admin_new_consent", url_for("admin.consents"), name=v["full_name"])
            audit("consent_uploaded", "consents", cid)
            flash(_("flash_consent_uploaded"), "success")
            return redirect(url_for("volunteer.consent"))
    return render_template("volunteer/consent.html", age=age, current=current, history=history, f=f, errors=errors)
