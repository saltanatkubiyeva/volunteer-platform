from datetime import date, datetime

from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

from . import friends as FR
from . import reviews as RV
from . import services as S
from .core import (IMAGE_EXT, DOC_EXT, _, age_on, audit, form_int, notify,
                   now_str, role_required, safe_next, save_upload)
from .db import execute, query, scalar, transaction
from .forms import Errors, clean, normalize_phone

bp = Blueprint("volunteer", __name__, url_prefix="/me")
volunteer_only = role_required("volunteer")

REG_SELECT = """SELECT r.*, e.title, e.starts_at, e.ends_at, e.address, e.status AS ev_status, e.cancel_reason,
    e.event_id, e.cover_path, o.name AS org_name, o.org_id,
    d.slug AS dir_slug, d.name_en AS dir_name_en, d.name_ru AS dir_name_ru, d.name_kk AS dir_name_kk, d.icon AS dir_icon, d.tone AS dir_tone,
    c.name_en AS city_name_en, c.name_ru AS city_name_ru, c.name_kk AS city_name_kk,
    ce.code AS cert_code, f.rating AS my_rating, f.status AS my_review_status,
    sh.title AS shift_title, sh.starts_at AS shift_start, sh.ends_at AS shift_end
    FROM registrations r JOIN events e USING (event_id) JOIN organizations o ON o.org_id = e.org_id
    LEFT JOIN event_shifts sh ON sh.shift_id = r.shift_id
    JOIN directions d ON d.direction_id = e.direction_id JOIN cities c ON c.city_id = e.city_id
    LEFT JOIN certificates ce ON ce.registration_id = r.registration_id
    LEFT JOIN feedback f ON f.registration_id = r.registration_id"""


@bp.context_processor
def friend_badge():
    if not g.get("volunteer"):
        return {}
    return dict(friend_requests=FR.incoming_count(g.volunteer["volunteer_id"]))


@bp.route("/friends")
@volunteer_only
def friends():
    vid = g.volunteer["volunteer_id"]
    tab = request.args.get("tab", "friends")
    incoming, outgoing = FR.requests(vid)
    met = FR.met(vid)
    return render_template("volunteer/friends.html", tab=tab, friends=FR.friends(vid), incoming=incoming,
                           outgoing=outgoing, met=met, wins=FR.recent_achievements(g.volunteer),
                           kudos_given=FR.kudos_given(vid), short_name=FR.short_name)


def _back(default_tab="friends"):
    return redirect(safe_next(request.form.get("next")) or url_for("volunteer.friends", tab=default_tab))


@bp.route("/friends/add/<int:volunteer_id>", methods=["POST"])
@volunteer_only
def friend_add(volunteer_id):
    try:
        result = FR.send(g.volunteer, volunteer_id)
        flash(_("flash_friend_" + result), "success")
    except S.RuleError as e:
        flash(_(e.key, **e.params), "error")
    return _back("met")


@bp.route("/friends/<int:friendship_id>/accept", methods=["POST"])
@volunteer_only
def friend_accept(friendship_id):
    try:
        FR.accept(g.volunteer, friendship_id)
        flash(_("flash_friend_friends"), "success")
    except S.RuleError as e:
        flash(_(e.key, **e.params), "error")
    return _back("requests")


@bp.route("/friends/<int:friendship_id>/remove", methods=["POST"])
@volunteer_only
def friend_remove(friendship_id):
    try:
        FR.remove(g.volunteer, friendship_id)
    except S.RuleError as e:
        flash(_(e.key, **e.params), "error")
    return _back()


@bp.route("/friends/kudos", methods=["POST"])
@volunteer_only
def friend_kudos():
    try:
        FR.give_kudos(g.volunteer, form_int("volunteer_id"), form_int("n"))
        flash(_("flash_kudos"), "success")
    except S.RuleError as e:
        flash(_(e.key, **e.params), "error")
    return _back()


@bp.route("/friends/settings", methods=["POST"])
@volunteer_only
def friend_settings():
    vals = [1 if request.form.get(k) else 0 for k in ("share_plans", "notify_friend_plans", "notify_friend_achievements")]
    execute("""UPDATE volunteers SET share_plans=?, notify_friend_plans=?, notify_friend_achievements=?
               WHERE volunteer_id=?""", vals + [g.volunteer["volunteer_id"]])
    flash(_("flash_saved"), "success")
    return redirect(url_for("auth.settings") + "#friends")


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
    age = age_on(g.volunteer["birth_date"])
    open_sql = S.EVENT_SELECT + f""" WHERE {S.PUBLIC_WHERE} AND e.status='published'
        AND e.registration_deadline >= ? AND e.min_age <= ?
        AND NOT EXISTS (SELECT 1 FROM registrations r WHERE r.event_id=e.event_id AND r.volunteer_id=?)
        AND (SELECT COUNT(*) FROM registrations r WHERE r.event_id=e.event_id AND r.status IN ('approved','attended')) < e.max_volunteers"""
    recommended = query(open_sql + f""" AND e.city_id = ?
        ORDER BY (e.direction_id IN ({marks})) DESC, e.starts_at LIMIT 3""",
                        [now, age, vid, g.volunteer["city_id"]] + my_dirs)
    rec_other_cities = False
    if not recommended:
        recommended = query(open_sql + f" AND e.direction_id IN ({marks}) ORDER BY e.starts_at LIMIT 3",
                            [now, age, vid] + my_dirs)
        rec_other_cities = bool(recommended)
    city_row = query("SELECT * FROM cities WHERE city_id=?", (g.volunteer["city_id"],), one=True)
    notifications = query("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC, notification_id DESC LIMIT 5",
                          (g.user["user_id"],))
    profile_missing = [k for k in ("about", "skills", "avatar_path") if not g.volunteer[k]]
    has_subs = bool(scalar("SELECT 1 FROM subscriptions WHERE volunteer_id=?", (vid,)))
    return render_template("volunteer/dashboard.html", milestones=S.milestone_certificates(vid),
                           friend_plans=FR.upcoming_with_friends(vid, 4), friend_wins=FR.recent_achievements(g.volunteer),
                           kudos_given=FR.kudos_given(vid),
                           has_subs=has_subs, for_you=S.new_for_you(g.volunteer, 3) if has_subs else [], upcoming=upcoming, to_review=to_review, recent=recent,
                           recommended=recommended, rec_other_cities=rec_other_cities, my_city=city_row, stats=S.volunteer_stats(vid), age=age,
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
    rows = query(REG_SELECT + f" WHERE r.volunteer_id=? AND e.deleted_at IS NULL AND {cond} ORDER BY {order}", [vid] + extra)
    counts = {k: scalar(f"SELECT COUNT(*) FROM registrations r JOIN events e USING (event_id) WHERE r.volunteer_id=? AND e.deleted_at IS NULL AND {c}",
                        [vid] + x) for k, (c, x, _o) in conditions.items()}
    waiting = query(S.EVENT_SELECT + """ JOIN waitlist w ON w.event_id = e.event_id
        WHERE w.volunteer_id=? AND e.status='published' AND e.starts_at > ? ORDER BY e.starts_at""", (vid, now))
    positions = {ev["event_id"]: S.waitlist_position(vid, ev["event_id"]) for ev in waiting}
    counts["active"] += len(waiting)
    return render_template("volunteer/applications.html", rows=rows, tab=tab, counts=counts,
                           waiting=waiting if tab == "active" else [], positions=positions)


@bp.route("/apply/<int:event_id>", methods=["POST"])
@volunteer_only
def apply(event_id):
    motivation = clean(request.form.get("motivation"), 500)
    ev = S.get_event(event_id)
    needed = {r["skill_id"] for r in S.event_requirements(event_id)} if ev else set()
    confirmed = {int(x) for x in request.form.getlist("has_doc") if x.isdigit()}
    if needed - confirmed:
        flash(_("err_confirm_documents"), "error")
        return redirect(url_for("public.event_detail", event_id=event_id))
    try:
        status = S.apply(g.volunteer, event_id, motivation, request.form.get("shift_pref"))
        flash(_("flash_applied_pending" if status == "pending" else "flash_applied_approved"), "success")
    except S.RuleError as e:
        flash(_(e.key, **e.params), "error")
    return redirect(url_for("public.event_detail", event_id=event_id))


@bp.route("/documents", methods=["GET", "POST"])
@volunteer_only
def documents():
    v = g.volunteer
    skills = query("SELECT * FROM skills ORDER BY skill_id")
    back = safe_next(request.values.get("next"))
    if request.method == "POST":
        skill = next((x for x in skills if str(x["skill_id"]) == request.form.get("skill_id", "")), None)
        if not skill:
            abort(400)
        expires = clean(request.form.get("expires_at"), 10) or None
        problem = None
        if skill["has_expiry"]:
            try:
                if not expires or datetime.strptime(expires, "%Y-%m-%d").date() <= date.today():
                    problem = "err_doc_expiry"
            except ValueError:
                problem = "err_doc_expiry"
        else:
            expires = None
        path = None
        if not problem:
            try:
                path = save_upload(request.files.get("document"), DOC_EXT, "documents")
                if not path:
                    problem = "err_file_required"
            except ValueError as e:
                problem = str(e)
        if problem:
            flash(_(problem), "error")
        else:
            S.save_document(v, skill["skill_id"], path, expires)
            flash(_("flash_document_uploaded"), "success")
            if back:
                return redirect(back)
        return redirect(url_for("volunteer.documents", skill=skill["skill_id"], next=back or None))
    docs = S.volunteer_documents(v["volunteer_id"])
    states = {sid: S.document_state(row) for sid, row in docs.items()}
    return render_template("volunteer/documents.html", skills=skills, docs=docs, states=states, back=back,
                           focus=request.args.get("skill", type=int), today=date.today().isoformat())


@bp.route("/waitlist/<int:event_id>", methods=["POST"])
@volunteer_only
def waitlist_join(event_id):
    try:
        pos = S.join_waitlist(g.volunteer, event_id, clean(request.form.get("motivation"), 500))
        flash(_("flash_waitlist_joined", n=pos), "success")
    except S.RuleError as e:
        flash(_(e.key, **e.params), "error")
    return redirect(url_for("public.event_detail", event_id=event_id))


@bp.route("/waitlist/<int:event_id>/leave", methods=["POST"])
@volunteer_only
def waitlist_leave(event_id):
    try:
        S.leave_waitlist(g.volunteer, event_id)
        flash(_("flash_waitlist_left"), "info")
    except S.RuleError as e:
        flash(_(e.key, **e.params), "error")
    return redirect(request.referrer or url_for("volunteer.applications"))


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
        status = RV.submit(registration_id, rating, clean(request.form.get("comment"), 600) or None)
        flash(_("flash_feedback_thanks") if status == "published" else _("flash_review_pending"),
              "success" if status == "published" else "info")
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


@bp.route("/milestones/<int:hours>", methods=["POST"])
@volunteer_only
def milestone_issue(hours):
    try:
        code = S.issue_milestone_certificate(g.volunteer, hours)
        return redirect(url_for("volunteer.certificate", code=code))
    except S.RuleError as e:
        flash(_(e.key, **e.params), "error")
        return redirect(url_for("volunteer.dashboard"))


@bp.route("/certificate/<code>")
@volunteer_only
def certificate(code):
    vid = g.volunteer["volunteer_id"]
    base = query("SELECT * FROM certificates WHERE code=?", (code,), one=True)
    if not base:
        abort(404)
    if base["type"] == "milestone":
        if base["volunteer_id"] != vid:
            abort(404)
        events = S.milestone_events(vid, base["issued_at"])
        return render_template("volunteer/milestone_certificate.html", cert=base, events=events,
                               hours=sum(e["hours_confirmed"] for e in events),
                               orgs=len({e["org_name"] for e in events}))
    cert = query("""SELECT ce.code, ce.issued_at, r.hours_confirmed, r.volunteer_id, r.is_team_lead, r.all_shifts,
        sh.title AS shift_title, sh.starts_at AS shift_start, sh.ends_at AS shift_end, v.full_name,
        e.title, e.starts_at, e.ends_at, e.address, o.name AS org_name, co.full_name AS confirmed_name,
        co.position AS confirmed_position, c.name_en AS city_name_en, c.name_ru AS city_name_ru, c.name_kk AS city_name_kk
        FROM certificates ce JOIN registrations r ON r.registration_id=ce.registration_id
        JOIN volunteers v ON v.volunteer_id=r.volunteer_id JOIN events e ON e.event_id=r.event_id
        JOIN organizations o ON o.org_id=e.org_id JOIN cities c ON c.city_id=e.city_id
        LEFT JOIN coordinators co ON co.coordinator_id=r.confirmed_by
        LEFT JOIN event_shifts sh ON sh.shift_id=r.shift_id WHERE ce.code=?""", (code,), one=True)
    if not cert or cert["volunteer_id"] != vid:
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
