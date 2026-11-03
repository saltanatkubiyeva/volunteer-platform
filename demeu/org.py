"""Organisation cabinet (coordinators): events, applications, attendance & hours,
organisation profile, team and reports."""
import csv
import io
from datetime import datetime, timedelta

from flask import (Blueprint, Response, abort, flash, g, redirect,
                   render_template, request, url_for)
from werkzeug.security import generate_password_hash

from . import services as S
from .core import (IMAGE_EXT, _, audit, duration_hours, form_int, notify,
                   now_str, role_required, save_upload)
from .db import execute, query, scalar, transaction
from .forms import (Errors, clean, normalize_phone, parse_local_dt,
                    password_problem, valid_email)

bp = Blueprint("org", __name__, url_prefix="/org")
coordinator_only = role_required("coordinator")


def owner_only():
    if not g.coordinator["is_owner"]:
        abort(403)


def own_event(event_id):
    ev = S.get_event(event_id)
    if not ev or ev["org_id"] != g.coordinator["org_id"]:
        abort(404)
    return ev


@bp.route("/")
@coordinator_only
def dashboard():
    oid = g.coordinator["org_id"]
    now = now_str()
    pending = query("""SELECT r.*, v.full_name, v.avatar_path, v.birth_date, v.volunteer_id, e.title, e.event_id, e.starts_at
        FROM registrations r JOIN volunteers v USING (volunteer_id) JOIN events e USING (event_id)
        WHERE e.org_id=? AND r.status='pending' AND e.status='published' AND e.starts_at > ?
        ORDER BY e.starts_at, r.applied_at LIMIT 8""", (oid, now))
    upcoming = query(S.EVENT_SELECT + " WHERE e.org_id=? AND e.status='published' AND e.ends_at >= ? ORDER BY e.starts_at LIMIT 5",
                     (oid, now))
    to_mark = query(S.EVENT_SELECT + """ WHERE e.org_id=? AND e.status='published' AND e.starts_at <= ?
        ORDER BY e.starts_at DESC""", (oid, now))
    return render_template("org/dashboard.html", pending=pending, upcoming=upcoming, to_mark=to_mark,
                           stats=S.org_stats(oid),
                           n_pending=scalar("""SELECT COUNT(*) FROM registrations r JOIN events e USING (event_id)
                               WHERE e.org_id=? AND r.status='pending' AND e.status='published' AND e.starts_at > ?""",
                                            (oid, now)))


@bp.route("/events")
@coordinator_only
def events():
    oid = g.coordinator["org_id"]
    tab = request.args.get("tab", "upcoming")
    now = now_str()
    conds = {
        "upcoming": ("e.status='published' AND e.ends_at >= ?", [now], "e.starts_at"),
        "drafts": ("e.status='draft'", [], "e.created_at DESC"),
        "past": ("e.status IN ('published','completed') AND e.ends_at < ?", [now], "e.starts_at DESC"),
        "cancelled": ("e.status='cancelled'", [], "e.starts_at DESC"),
    }
    cond, args, order = conds.get(tab, conds["upcoming"])
    rows = query(S.EVENT_SELECT + f" WHERE e.org_id=? AND {cond} ORDER BY {order}", [oid] + args)
    counts = {k: scalar(f"SELECT COUNT(*) FROM events e WHERE e.org_id=? AND {c}", [oid] + a)
              for k, (c, a, _o) in conds.items()}
    return render_template("org/events.html", rows=rows, tab=tab, counts=counts)


EVENT_FIELDS = ("title", "summary", "description", "address", "requirements", "provided")


def _event_form(ev=None):
    oid = g.coordinator["org_id"]
    errors = Errors()
    team = query("SELECT * FROM coordinators WHERE org_id=? ORDER BY full_name", (oid,))
    ref = dict(cities=query("SELECT * FROM cities ORDER BY name_en"),
               directions=query("SELECT * FROM directions ORDER BY direction_id"), team=team)
    taken = ev["taken"] if ev else 0
    if ev:
        f = dict(ev)
        for k in ("starts_at", "ends_at", "registration_deadline"):
            f[k] = (f[k] or "").replace(" ", "T")
    else:
        start = (datetime.now() + timedelta(days=10)).replace(hour=10, minute=0)
        f = dict(starts_at=start.strftime("%Y-%m-%dT%H:%M"),
                 ends_at=(start + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M"),
                 registration_deadline=(start - timedelta(days=1)).replace(hour=20).strftime("%Y-%m-%dT%H:%M"),
                 max_volunteers=20, min_age=14, requires_approval=1, city_id=g.org["city_id"],
                 coordinator_id=g.coordinator["coordinator_id"])
    if request.method == "POST":
        for k in EVENT_FIELDS:
            f[k] = clean(request.form.get(k), 4000 if k == "description" else 600)
        for k in ("starts_at", "ends_at", "registration_deadline"):
            f[k] = clean(request.form.get(k), 20)
        f["direction_id"], f["city_id"] = form_int("direction_id"), form_int("city_id")
        f["coordinator_id"] = form_int("coordinator_id")
        f["max_volunteers"], f["min_age"] = form_int("max_volunteers"), form_int("min_age")
        f["requires_approval"] = 1 if request.form.get("requires_approval") else 0
        publish = request.form.get("action") == "publish"

        if len(f["title"]) < 5:
            errors.add("title", "err_title")
        if len(f["summary"]) < 10:
            errors.add("summary", "err_summary")
        if len(f["description"]) < 40:
            errors.add("description", "err_description_short")
        if len(f["address"]) < 5:
            errors.add("address", "err_required")
        if not f["direction_id"] or not scalar("SELECT 1 FROM directions WHERE direction_id=?", (f["direction_id"],)):
            errors.add("direction_id", "err_required")
        if not f["city_id"] or not scalar("SELECT 1 FROM cities WHERE city_id=?", (f["city_id"],)):
            errors.add("city_id", "err_city")
        if not any(t["coordinator_id"] == f["coordinator_id"] for t in team):
            errors.add("coordinator_id", "err_required")
        st, en, dl = (parse_local_dt(f[k]) for k in ("starts_at", "ends_at", "registration_deadline"))
        if not st:
            errors.add("starts_at", "err_date")
        elif st <= datetime.now():
            errors.add("starts_at", "err_start_future")
        if not en:
            errors.add("ends_at", "err_date")
        elif st and en <= st:
            errors.add("ends_at", "err_end_after_start")
        elif st and (en - st) > timedelta(hours=12):
            errors.add("ends_at", "err_duration")
        if not dl:
            errors.add("registration_deadline", "err_date")
        elif st and dl > st:
            errors.add("registration_deadline", "err_deadline")
        if not f["max_volunteers"] or not 1 <= f["max_volunteers"] <= 1000:
            errors.add("max_volunteers", "err_capacity")
        elif f["max_volunteers"] < taken:
            errors.add("max_volunteers", "err_capacity_taken")
        if f["min_age"] is None or not 14 <= f["min_age"] <= 99:
            errors.add("min_age", "err_min_age")
        if publish and g.org["status"] != "verified":
            errors.add("form", "err_org_not_verified")
        cover = ev["cover_path"] if ev else None
        try:
            new_cover = save_upload(request.files.get("cover"), IMAGE_EXT, "covers")
            if new_cover:
                cover = new_cover
        except ValueError as e:
            errors.add("cover", str(e))
        if request.form.get("remove_cover"):
            cover = None

        if not errors:
            values = (f["title"], f["summary"], f["description"], f["address"], f["requirements"] or None,
                      f["provided"] or None, f["direction_id"], f["city_id"], f["coordinator_id"],
                      st.strftime("%Y-%m-%d %H:%M"), en.strftime("%Y-%m-%d %H:%M"), dl.strftime("%Y-%m-%d %H:%M"),
                      f["max_volunteers"], f["min_age"], f["requires_approval"], cover)
            if ev is None:
                status = "published" if publish else "draft"
                with transaction():
                    new_id = execute("""INSERT INTO events (title, summary, description, address, requirements, provided,
                        direction_id, city_id, coordinator_id, starts_at, ends_at, registration_deadline, max_volunteers,
                        min_age, requires_approval, cover_path, org_id, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                     values + (g.coordinator["org_id"], status))
                    audit("event_created", "events", new_id, None, status)
                flash(_("flash_event_published" if publish else "flash_event_draft"), "success")
                return None, new_id
            status = "published" if (publish or ev["status"] == "published") else "draft"
            with transaction():
                execute("""UPDATE events SET title=?, summary=?, description=?, address=?, requirements=?, provided=?,
                    direction_id=?, city_id=?, coordinator_id=?, starts_at=?, ends_at=?, registration_deadline=?,
                    max_volunteers=?, min_age=?, requires_approval=?, cover_path=?, status=?, updated_at=?
                    WHERE event_id=?""", values + (status, now_str(), ev["event_id"]))
                changed = (ev["starts_at"] != values[9] or ev["ends_at"] != values[10] or ev["address"] != values[3]
                           or ev["city_id"] != values[7])
                if changed and ev["status"] == "published":
                    for r in query("""SELECT v.user_id FROM registrations r JOIN volunteers v USING (volunteer_id)
                                      WHERE r.event_id=? AND r.status IN ('pending','approved')""", (ev["event_id"],)):
                        notify(r["user_id"], "n_event_changed", url_for("public.event_detail", event_id=ev["event_id"]),
                               event=f["title"])
                audit("event_updated", "events", ev["event_id"], ev["status"], status)
            flash(_("flash_event_saved"), "success")
            return None, ev["event_id"]
    return render_template("org/event_form.html", f=f, ev=ev, errors=errors, **ref), None


@bp.route("/events/new", methods=["GET", "POST"])
@coordinator_only
def event_new():
    page, new_id = _event_form()
    return page if page is not None else redirect(url_for("org.event_manage", event_id=new_id))


@bp.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
@coordinator_only
def event_edit(event_id):
    ev = own_event(event_id)
    if ev["status"] not in ("draft", "published") or ev["starts_at"] <= now_str():
        flash(_("rule_cannot_edit"), "error")
        return redirect(url_for("org.event_manage", event_id=event_id))
    page, _id = _event_form(ev)
    return page if page is not None else redirect(url_for("org.event_manage", event_id=event_id))


@bp.route("/events/<int:event_id>")
@coordinator_only
def event_manage(event_id):
    ev = own_event(event_id)
    regs = query("""SELECT r.*, v.full_name, v.phone, v.birth_date, v.avatar_path, v.volunteer_id, u.email,
        (SELECT COUNT(*) FROM registrations r2 WHERE r2.volunteer_id=v.volunteer_id AND r2.status='attended') AS done,
        (SELECT COUNT(*) FROM registrations r2 WHERE r2.volunteer_id=v.volunteer_id AND r2.status='no_show') AS missed
        FROM registrations r JOIN volunteers v USING (volunteer_id) JOIN users u ON u.user_id=v.user_id
        WHERE r.event_id=? ORDER BY r.applied_at""", (event_id,))
    groups = {k: [r for r in regs if r["status"] in v] for k, v in {
        "pending": ("pending",), "participants": ("approved", "attended", "no_show"),
        "closed": ("rejected", "cancelled")}.items()}
    started = ev["starts_at"] <= now_str()
    tab = request.args.get("tab") or ("attendance" if started and ev["status"] == "published" else "pending")
    return render_template("org/event_manage.html", ev=ev, groups=groups, tab=tab, started=started,
                           finished=ev["ends_at"] <= now_str(),
                           hours=duration_hours(ev["starts_at"], ev["ends_at"]),
                           unmarked=sum(1 for r in regs if r["status"] == "approved"))


@bp.route("/registrations/<int:registration_id>/decide", methods=["POST"])
@coordinator_only
def decide(registration_id):
    approve = request.form.get("decision") == "approve"
    try:
        S.decide(g.coordinator, registration_id, approve, clean(request.form.get("note"), 300))
        flash(_("flash_approved" if approve else "flash_rejected"), "success")
    except S.RuleError as e:
        flash(_(e.key, **e.params), "error")
    return redirect(request.referrer or url_for("org.dashboard"))


@bp.route("/events/<int:event_id>/attendance", methods=["POST"])
@coordinator_only
def attendance(event_id):
    own_event(event_id)
    ids = [int(x) for x in request.form.getlist("registration_id") if x.isdigit()]
    done, problems = 0, []
    for rid in ids:
        mark = request.form.get(f"mark_{rid}")
        if mark not in ("attended", "no_show"):
            continue
        hours = None
        try:
            hours = float(request.form.get(f"hours_{rid}", "").replace(",", "."))
        except ValueError:
            pass
        try:
            S.mark_attendance(g.coordinator, rid, mark == "attended", hours)
            done += 1
        except S.RuleError as e:
            problems.append(_(e.key, **e.params))
    if done:
        flash(_("flash_attendance_saved", n=done), "success")
    for p in sorted(set(problems)):
        flash(p, "error")
    return redirect(url_for("org.event_manage", event_id=event_id, tab="attendance"))


@bp.route("/events/<int:event_id>/complete", methods=["POST"])
@coordinator_only
def complete(event_id):
    try:
        S.complete_event(g.coordinator, event_id)
        flash(_("flash_event_completed"), "success")
    except S.RuleError as e:
        flash(_(e.key, **e.params), "error")
    return redirect(url_for("org.event_manage", event_id=event_id))


@bp.route("/events/<int:event_id>/cancel", methods=["POST"])
@coordinator_only
def cancel(event_id):
    own_event(event_id)
    reason = clean(request.form.get("reason"), 300)
    if len(reason) < 5:
        flash(_("err_cancel_reason"), "error")
        return redirect(url_for("org.event_manage", event_id=event_id))
    try:
        S.cancel_event(g.user["user_id"], event_id, reason)
        flash(_("flash_event_cancelled"), "info")
    except S.RuleError as e:
        flash(_(e.key, **e.params), "error")
    return redirect(url_for("org.event_manage", event_id=event_id))


@bp.route("/events/<int:event_id>/export.csv")
@coordinator_only
def export(event_id):
    ev = own_event(event_id)
    rows = query("""SELECT v.full_name, v.phone, u.email, v.birth_date, r.status, r.applied_at, r.hours_confirmed
        FROM registrations r JOIN volunteers v USING (volunteer_id) JOIN users u ON u.user_id=v.user_id
        WHERE r.event_id=? AND r.status IN ('pending','approved','attended','no_show') ORDER BY v.full_name""", (event_id,))
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel opens Cyrillic correctly
    w = csv.writer(buf)
    w.writerow(["Full name", "Phone", "Email", "Birth date", "Status", "Applied at", "Confirmed hours"])
    for r in rows:
        w.writerow([r["full_name"], r["phone"], r["email"], r["birth_date"], r["status"], r["applied_at"],
                    r["hours_confirmed"] or ""])
    audit("participants_exported", "events", event_id)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=event_{ev['event_id']}_participants.csv"})


# --------------------------------------------------------------------- organisation profile & team
@bp.route("/profile", methods=["GET", "POST"])
@coordinator_only
def profile():
    owner_only()
    o = g.org
    errors = Errors()
    f = dict(o)
    selected = [r["direction_id"] for r in query("SELECT direction_id FROM organization_directions WHERE org_id=?",
                                                  (o["org_id"],))]
    if request.method == "POST":
        f.update({k: clean(request.form.get(k), 3000 if k == "description" else 200)
                  for k in ("description", "address", "email", "phone", "website")})
        f["city_id"] = form_int("city_id")
        f["founded_year"] = form_int("founded_year")
        selected = [int(x) for x in request.form.getlist("directions") if x.isdigit()]
        editable_name = o["status"] != "verified"
        if editable_name:
            f["name"] = clean(request.form.get("name"), 200)
            if len(f["name"]) < 3:
                errors.add("name", "err_required")
            elif scalar("SELECT 1 FROM organizations WHERE name=? AND org_id<>?", (f["name"], o["org_id"])):
                errors.add("name", "err_org_name_taken")
        if len(f["description"]) < 40:
            errors.add("description", "err_description_short")
        if len(f["address"]) < 5:
            errors.add("address", "err_required")
        if not valid_email(f["email"]):
            errors.add("email", "err_email")
        phone = normalize_phone(f["phone"])
        if not phone:
            errors.add("phone", "err_phone")
        if f["website"] and not f["website"].startswith(("http://", "https://")):
            f["website"] = "https://" + f["website"]
        if not f["city_id"] or not scalar("SELECT 1 FROM cities WHERE city_id=?", (f["city_id"],)):
            errors.add("city_id", "err_city")
        if f["founded_year"] and not 1950 <= f["founded_year"] <= datetime.now().year:
            errors.add("founded_year", "err_year")
        if not selected:
            errors.add("directions", "err_directions")
        logo = o["logo_path"]
        try:
            new_logo = save_upload(request.files.get("logo"), IMAGE_EXT, "logos")
            if new_logo:
                logo = new_logo
        except ValueError as e:
            errors.add("logo", str(e))
        if not errors:
            with transaction():
                execute("""UPDATE organizations SET name=?, description=?, address=?, email=?, phone=?, website=?,
                           city_id=?, founded_year=?, logo_path=? WHERE org_id=?""",
                        (f["name"], f["description"], f["address"], f["email"], phone, f["website"] or None,
                         f["city_id"], f["founded_year"], logo, o["org_id"]))
                execute("DELETE FROM organization_directions WHERE org_id=?", (o["org_id"],))
                for d in set(selected):
                    if scalar("SELECT 1 FROM directions WHERE direction_id=?", (d,)):
                        execute("INSERT INTO organization_directions VALUES (?,?)", (o["org_id"], d))
                if o["status"] == "rejected":  # resubmit for review after fixing
                    execute("UPDATE organizations SET status='pending', status_comment=NULL WHERE org_id=?", (o["org_id"],))
                    for admin in query("SELECT user_id FROM users WHERE role='admin' AND is_active=1"):
                        notify(admin["user_id"], "n_admin_new_org", url_for("admin.org_review", org_id=o["org_id"]),
                               org=f["name"])
            flash(_("flash_profile_saved"), "success")
            return redirect(url_for("public.organization_profile", org_id=o["org_id"]))
    return render_template("org/profile.html", f=f, errors=errors, selected=selected,
                           cities=query("SELECT * FROM cities ORDER BY name_en"),
                           directions=query("SELECT * FROM directions ORDER BY direction_id"))


@bp.route("/team", methods=["GET", "POST"])
@coordinator_only
def team():
    owner_only()
    oid = g.coordinator["org_id"]
    errors, f = Errors(), {}
    if request.method == "POST":
        f = {k: clean(request.form.get(k), 120) for k in ("full_name", "email", "phone", "position")}
        f["email"] = f["email"].lower()
        pw = request.form.get("password", "")
        if len(f["full_name"]) < 3:
            errors.add("full_name", "err_name")
        if not valid_email(f["email"]):
            errors.add("email", "err_email")
        elif scalar("SELECT 1 FROM users WHERE email=?", (f["email"],)):
            errors.add("email", "err_email_taken")
        phone = normalize_phone(f["phone"])
        if not phone:
            errors.add("phone", "err_phone")
        problem = password_problem(pw)
        if problem:
            errors.add("password", problem)
        if not errors:
            with transaction():
                uid = execute("INSERT INTO users (email, password_hash, role, preferred_lang) VALUES (?,?,?,?)",
                              (f["email"], generate_password_hash(pw), "coordinator", g.lang))
                cid = execute("INSERT INTO coordinators (user_id, org_id, full_name, phone, position) VALUES (?,?,?,?,?)",
                              (uid, oid, f["full_name"], phone, f["position"] or None))
                notify(uid, "n_team_added", url_for("org.dashboard"), org=g.org["name"])
                audit("coordinator_added", "coordinators", cid)
            flash(_("flash_team_added"), "success")
            return redirect(url_for("org.team"))
    members = query("""SELECT c.*, u.email, u.is_active, u.last_login_at,
        (SELECT COUNT(*) FROM events e WHERE e.coordinator_id=c.coordinator_id AND e.status IN ('draft','published')) AS active_events
        FROM coordinators c JOIN users u USING (user_id) WHERE c.org_id=? ORDER BY c.is_owner DESC, c.full_name""", (oid,))
    return render_template("org/team.html", members=members, f=f, errors=errors)


@bp.route("/team/<int:coordinator_id>/toggle", methods=["POST"])
@coordinator_only
def team_toggle(coordinator_id):
    owner_only()
    c = query("SELECT * FROM coordinators WHERE coordinator_id=? AND org_id=?",
              (coordinator_id, g.coordinator["org_id"]), one=True)
    if not c or c["is_owner"]:
        abort(400)
    active = scalar("SELECT is_active FROM users WHERE user_id=?", (c["user_id"],))
    if active and scalar("SELECT COUNT(*) FROM events WHERE coordinator_id=? AND status IN ('draft','published')"
                         " AND ends_at >= ?", (coordinator_id, now_str())):
        flash(_("rule_coordinator_has_events"), "error")
        return redirect(url_for("org.team"))
    execute("UPDATE users SET is_active=? WHERE user_id=?", (0 if active else 1, c["user_id"]))
    audit("coordinator_" + ("deactivated" if active else "activated"), "coordinators", coordinator_id)
    flash(_("flash_saved"), "success")
    return redirect(url_for("org.team"))


@bp.route("/reports")
@coordinator_only
def reports():
    oid = g.coordinator["org_id"]
    rows = query("""SELECT e.event_id, e.title, e.starts_at, e.status, e.max_volunteers,
        SUM(r.status IS NOT NULL) AS applied, SUM(r.status IN ('approved','attended','no_show')) AS accepted,
        SUM(r.status='attended') AS attended, SUM(r.status='no_show') AS no_show,
        COALESCE(SUM(CASE WHEN r.status='attended' THEN r.hours_confirmed END),0) AS hours,
        (SELECT ROUND(AVG(f.rating),1) FROM feedback f JOIN registrations r2 USING (registration_id)
          WHERE r2.event_id=e.event_id AND f.is_hidden=0) AS rating
        FROM events e LEFT JOIN registrations r ON r.event_id=e.event_id
        WHERE e.org_id=? AND e.status IN ('published','completed') AND e.starts_at <= ?
        GROUP BY e.event_id ORDER BY e.starts_at DESC""", (oid, now_str()))
    if request.args.get("format") == "csv":
        buf = io.StringIO()
        buf.write("﻿")
        w = csv.writer(buf)
        w.writerow(["Event", "Date", "Places", "Applied", "Accepted", "Attended", "No-show", "Hours", "Rating"])
        for r in rows:
            w.writerow([r["title"], r["starts_at"], r["max_volunteers"], r["applied"] or 0, r["accepted"] or 0,
                        r["attended"] or 0, r["no_show"] or 0, r["hours"], r["rating"] or ""])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=demeu_org_report.csv"})
    return render_template("org/reports.html", rows=rows, stats=S.org_stats(oid))
