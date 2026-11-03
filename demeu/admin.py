"""Admin panel: dashboard, verification queues, generic CRUD over every table
(constraints of the database are reported as readable messages), audit log."""
import sqlite3

from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)
from werkzeug.security import generate_password_hash

from . import services as S
from .core import (Page, _, audit, notify, now_str, page_arg, role_required)
from .db import execute, get_db, query, scalar, transaction
from .forms import Errors, clean, password_problem, valid_email

bp = Blueprint("admin", __name__, url_prefix="/admin")
admin_only = role_required("admin")


def F(name, kind="text", required=False, **kw):
    return dict(name=name, kind=kind, required=required, **kw)


STATUS_ORG = ("pending", "verified", "rejected", "suspended")
STATUS_EVENT = ("draft", "published", "cancelled", "completed")
STATUS_REG = ("pending", "approved", "rejected", "cancelled", "attended", "no_show")
TONES = ("mint", "sage", "butter", "sky", "rose", "lilac")

# Every table the admin can manage. list_sql must expose the pk column and the list columns.
ENTITIES = {
    "users": dict(
        table="users", pk="user_id", icon="lock", create=False,
        list_sql="SELECT * FROM users", search=("email",), filters={"role": ("volunteer", "coordinator", "admin")},
        columns=("user_id", "email", "role", "is_active", "preferred_lang", "last_login_at"),
        fields=[F("email", "email", True), F("is_active", "bool"),
                F("preferred_lang", "select", True, choices=("en", "ru", "kk"))]),
    "volunteers": dict(
        table="volunteers", pk="volunteer_id", icon="users", create=False,
        list_sql="""SELECT v.*, c.name_en AS city, u.email FROM volunteers v JOIN cities c USING (city_id)
                    JOIN users u USING (user_id)""",
        search=("v.full_name", "u.email", "v.phone"), columns=("volunteer_id", "full_name", "email", "phone", "city", "birth_date", "is_public"),
        fields=[F("full_name", required=True), F("phone", required=True), F("birth_date", "date", True),
                F("city_id", "fk", True, ref=("cities", "city_id", "name_en")), F("about", "textarea"),
                F("skills", "textarea"), F("is_public", "bool"), F("show_contacts", "bool")]),
    "organizations": dict(
        table="organizations", pk="org_id", icon="building", create=False,
        list_sql="SELECT o.*, c.name_en AS city FROM organizations o JOIN cities c USING (city_id)",
        search=("o.name", "o.bin", "o.email"), filters={"status": STATUS_ORG},
        columns=("org_id", "name", "bin", "org_type", "city", "status", "created_at"),
        fields=[F("name", required=True), F("bin", required=True),
                F("org_type", "select", True, choices=("ngo", "foundation", "initiative", "university", "government", "business")),
                F("description", "textarea", True), F("city_id", "fk", True, ref=("cities", "city_id", "name_en")),
                F("address", required=True), F("email", "email", True), F("phone", required=True), F("website"),
                F("founded_year", "int"), F("status", "select", True, choices=STATUS_ORG), F("status_comment", "textarea")]),
    "coordinators": dict(
        table="coordinators", pk="coordinator_id", icon="briefcase", create=False,
        list_sql="""SELECT c.*, o.name AS organization, u.email FROM coordinators c
                    JOIN organizations o USING (org_id) JOIN users u USING (user_id)""",
        search=("c.full_name", "u.email", "o.name"),
        columns=("coordinator_id", "full_name", "email", "organization", "position", "is_owner"),
        fields=[F("full_name", required=True), F("phone", required=True), F("position"),
                F("org_id", "fk", True, ref=("organizations", "org_id", "name")), F("is_owner", "bool")]),
    "events": dict(
        table="events", pk="event_id", icon="calendar", create=False,
        list_sql="""SELECT e.*, o.name AS organization, c.name_en AS city FROM events e
                    JOIN organizations o USING (org_id) JOIN cities c USING (city_id)""",
        search=("e.title", "o.name", "e.address"), filters={"status": STATUS_EVENT},
        columns=("event_id", "title", "organization", "city", "starts_at", "max_volunteers", "status"),
        fields=[F("title", required=True), F("summary", required=True), F("description", "textarea", True),
                F("direction_id", "fk", True, ref=("directions", "direction_id", "name_en")),
                F("city_id", "fk", True, ref=("cities", "city_id", "name_en")), F("address", required=True),
                F("starts_at", "datetime", True), F("ends_at", "datetime", True),
                F("registration_deadline", "datetime", True), F("max_volunteers", "int", True),
                F("min_age", "int", True), F("requires_approval", "bool"), F("requirements", "textarea"),
                F("provided", "textarea"), F("status", "select", True, choices=STATUS_EVENT),
                F("cancel_reason", "textarea")]),
    "registrations": dict(
        table="registrations", pk="registration_id", icon="clipboard-check", create=False,
        list_sql="""SELECT r.*, v.full_name AS volunteer, e.title AS event FROM registrations r
                    JOIN volunteers v USING (volunteer_id) JOIN events e USING (event_id)""",
        search=("v.full_name", "e.title"), filters={"status": STATUS_REG},
        columns=("registration_id", "volunteer", "event", "status", "applied_at", "hours_confirmed"),
        fields=[F("status", "select", True, choices=STATUS_REG), F("hours_confirmed", "real"),
                F("decision_note", "textarea")]),
    "consents": dict(
        table="consents", pk="consent_id", icon="file-text", create=False,
        list_sql="SELECT c.*, v.full_name AS volunteer FROM consents c JOIN volunteers v USING (volunteer_id)",
        search=("v.full_name", "c.parent_name"), filters={"status": ("pending", "approved", "rejected")},
        columns=("consent_id", "volunteer", "parent_name", "parent_phone", "status", "uploaded_at"),
        fields=[F("parent_name", required=True), F("parent_phone", required=True),
                F("status", "select", True, choices=("pending", "approved", "rejected")), F("review_comment", "textarea")]),
    "feedback": dict(
        table="feedback", pk="feedback_id", icon="star", create=False,
        list_sql="""SELECT f.*, v.full_name AS volunteer, e.title AS event FROM feedback f
                    JOIN registrations r USING (registration_id) JOIN volunteers v USING (volunteer_id)
                    JOIN events e USING (event_id)""",
        search=("f.comment", "v.full_name", "e.title"),
        columns=("feedback_id", "volunteer", "event", "rating", "comment", "is_hidden"),
        fields=[F("rating", "int", True), F("comment", "textarea"), F("is_hidden", "bool")]),
    "certificates": dict(
        table="certificates", pk="certificate_id", icon="award", create=False, edit=False,
        list_sql="""SELECT ce.*, v.full_name AS volunteer, e.title AS event FROM certificates ce
                    JOIN registrations r USING (registration_id) JOIN volunteers v USING (volunteer_id)
                    JOIN events e USING (event_id)""",
        search=("ce.code", "v.full_name"), columns=("certificate_id", "code", "volunteer", "event", "issued_at"),
        fields=[]),
    "directions": dict(
        table="directions", pk="direction_id", icon="target", create=True,
        list_sql="SELECT * FROM directions", search=("name_en", "name_ru", "name_kk"),
        columns=("direction_id", "slug", "name_en", "name_ru", "name_kk", "tone"),
        fields=[F("slug", required=True), F("name_en", required=True), F("name_ru", required=True),
                F("name_kk", required=True), F("icon", required=True), F("tone", "select", True, choices=TONES)]),
    "cities": dict(
        table="cities", pk="city_id", icon="map-pin", create=True,
        list_sql="SELECT * FROM cities", search=("name_en", "name_ru", "name_kk"),
        columns=("city_id", "name_en", "name_ru", "name_kk", "region_en"),
        fields=[F("name_en", required=True), F("name_ru", required=True), F("name_kk", required=True),
                F("region_en", required=True), F("lat", "real"), F("lng", "real")]),
    "offices": dict(
        table="offices", pk="office_id", icon="home", create=True,
        list_sql="SELECT o.*, c.name_en AS city FROM offices o JOIN cities c USING (city_id)",
        search=("o.address", "c.name_en"), columns=("office_id", "city", "is_head", "address", "phone"),
        fields=[F("city_id", "fk", True, ref=("cities", "city_id", "name_en")), F("is_head", "bool"),
                F("address", required=True), F("phone", required=True), F("email", "email", True),
                F("hours", required=True), F("lat", "real", True), F("lng", "real", True)]),
    "messages": dict(
        table="contact_messages", pk="message_id", icon="inbox", create=False,
        list_sql="SELECT * FROM contact_messages", search=("name", "email", "message"),
        filters={"status": ("new", "in_progress", "closed")},
        columns=("message_id", "name", "email", "topic", "status", "created_at"),
        fields=[F("status", "select", True, choices=("new", "in_progress", "closed"))]),
}
NAV_GROUPS = [
    ("adm_group_people", ["users", "volunteers", "coordinators"]),
    ("adm_group_activity", ["organizations", "events", "registrations", "consents", "feedback", "certificates"]),
    ("adm_group_reference", ["directions", "cities", "offices"]),
]


def friendly_db_error(err):
    msg = str(err)
    if "FOREIGN KEY" in msg:
        return _("db_err_fk")
    if "UNIQUE" in msg:
        return _("db_err_unique", detail=msg.split(":")[-1].strip())
    if "CHECK" in msg:
        return _("db_err_check", detail=msg.split(":")[-1].strip())
    if "NOT NULL" in msg:
        return _("db_err_notnull", detail=msg.split(":")[-1].strip())
    return msg


@bp.context_processor
def admin_ctx():
    counts = dict(
        organizations=scalar("SELECT COUNT(*) FROM organizations WHERE status='pending'"),
        consents=scalar("SELECT COUNT(*) FROM consents WHERE status='pending'"),
        messages=scalar("SELECT COUNT(*) FROM contact_messages WHERE status='new'"),
    )
    return dict(ENTITIES=ENTITIES, NAV_GROUPS=NAV_GROUPS, queue_counts=counts)


# --------------------------------------------------------------------- dashboard
@bp.route("/")
@admin_only
def dashboard():
    k = dict(
        users=scalar("SELECT COUNT(*) FROM users"),
        volunteers=scalar("SELECT COUNT(*) FROM volunteers"),
        orgs=scalar("SELECT COUNT(*) FROM organizations WHERE status='verified'"),
        events_open=scalar("SELECT COUNT(*) FROM events WHERE status='published' AND ends_at >= ?", (now_str(),)),
        hours=scalar("SELECT COALESCE(SUM(hours_confirmed),0) FROM registrations WHERE status='attended'"),
        apps_30=scalar("SELECT COUNT(*) FROM registrations WHERE applied_at >= datetime('now','localtime','-30 days')"),
        new_users_30=scalar("SELECT COUNT(*) FROM users WHERE created_at >= datetime('now','localtime','-30 days')"),
    )
    pending_orgs = query("""SELECT o.*, c.name_en AS city FROM organizations o JOIN cities c USING (city_id)
                            WHERE o.status='pending' ORDER BY o.created_at""")
    pending_consents = query("""SELECT c.*, v.full_name, v.birth_date FROM consents c JOIN volunteers v USING (volunteer_id)
                                WHERE c.status='pending' ORDER BY c.uploaded_at""")
    new_messages = query("SELECT * FROM contact_messages WHERE status='new' ORDER BY created_at DESC LIMIT 5")
    recent_audit = query("""SELECT a.*, u.email FROM audit_log a LEFT JOIN users u USING (user_id)
                            ORDER BY a.created_at DESC, a.log_id DESC LIMIT 8""")
    daily = query("""SELECT date(applied_at) AS d, COUNT(*) AS n FROM registrations
                     WHERE applied_at >= date('now','localtime','-13 days') GROUP BY d ORDER BY d""")
    return render_template("admin/dashboard.html", k=k, pending_orgs=pending_orgs, pending_consents=pending_consents,
                           new_messages=new_messages, recent_audit=recent_audit, daily=daily)


# --------------------------------------------------------------------- verification queues
@bp.route("/organizations/<int:org_id>/review", methods=["GET", "POST"])
@admin_only
def org_review(org_id):
    o = query("""SELECT o.*, c.name_en AS city_name_en, c.name_ru AS city_name_ru, c.name_kk AS city_name_kk
                 FROM organizations o JOIN cities c USING (city_id) WHERE org_id=?""", (org_id,), one=True)
    if not o:
        abort(404)
    if request.method == "POST":
        action = request.form.get("action")
        comment = clean(request.form.get("comment"), 500)
        new = {"verify": "verified", "reject": "rejected", "suspend": "suspended", "restore": "verified"}.get(action)
        if not new:
            abort(400)
        if new in ("rejected", "suspended") and len(comment) < 5:
            flash(_("err_comment_required"), "error")
            return redirect(url_for("admin.org_review", org_id=org_id))
        with transaction():
            execute("""UPDATE organizations SET status=?, status_comment=?, verified_at=CASE WHEN ?='verified'
                       THEN ? ELSE verified_at END, verified_by=CASE WHEN ?='verified' THEN ? ELSE verified_by END
                       WHERE org_id=?""", (new, comment or None, new, now_str(), new, g.user["user_id"], org_id))
            audit("org_" + new, "organizations", org_id, o["status"], new)
            for c in query("SELECT user_id FROM coordinators WHERE org_id=?", (org_id,)):
                notify(c["user_id"], "n_org_" + new, url_for("org.dashboard"), reason=comment)
        flash(_("flash_saved"), "success")
        return redirect(url_for("admin.org_review", org_id=org_id))
    staff = query("""SELECT c.*, u.email FROM coordinators c JOIN users u USING (user_id) WHERE org_id=?""", (org_id,))
    dirs = query("""SELECT d.* FROM organization_directions od JOIN directions d USING (direction_id) WHERE od.org_id=?""",
                 (org_id,))
    events = query("SELECT * FROM events WHERE org_id=? ORDER BY starts_at DESC LIMIT 10", (org_id,))
    return render_template("admin/org_review.html", o=o, staff=staff, dirs=dirs, events=events)


@bp.route("/consents/queue", methods=["GET", "POST"])
@admin_only
def consents():
    if request.method == "POST":
        cid = int(request.form.get("consent_id", 0))
        action = request.form.get("action")
        comment = clean(request.form.get("comment"), 300)
        c = query("SELECT c.*, v.user_id FROM consents c JOIN volunteers v USING (volunteer_id) WHERE consent_id=?",
                  (cid,), one=True)
        if not c or c["status"] != "pending" or action not in ("approve", "reject"):
            abort(400)
        if action == "reject" and len(comment) < 5:
            flash(_("err_comment_required"), "error")
            return redirect(url_for("admin.consents"))
        new = "approved" if action == "approve" else "rejected"
        execute("UPDATE consents SET status=?, review_comment=?, reviewed_by=?, reviewed_at=? WHERE consent_id=?",
                (new, comment or None, g.user["user_id"], now_str(), cid))
        audit("consent_" + new, "consents", cid, "pending", new)
        notify(c["user_id"], "n_consent_" + new, url_for("volunteer.consent"), reason=comment)
        flash(_("flash_saved"), "success")
        return redirect(url_for("admin.consents"))
    rows = query("""SELECT c.*, v.full_name, v.birth_date, v.volunteer_id FROM consents c JOIN volunteers v USING (volunteer_id)
                    ORDER BY c.status='pending' DESC, c.uploaded_at DESC LIMIT 50""")
    return render_template("admin/consents.html", rows=rows)


@bp.route("/messages")
@admin_only
def messages():
    rows = query("SELECT * FROM contact_messages ORDER BY status='new' DESC, created_at DESC LIMIT 100")
    return render_template("admin/messages.html", rows=rows)


@bp.route("/messages/<int:message_id>/status", methods=["POST"])
@admin_only
def message_status(message_id):
    st = request.form.get("status")
    if st in ("new", "in_progress", "closed"):
        execute("UPDATE contact_messages SET status=? WHERE message_id=?", (st, message_id))
    return redirect(url_for("admin.messages"))


@bp.route("/audit")
@admin_only
def audit_log():
    entity = request.args.get("entity", "")
    where, args = [], []
    if entity:
        where.append("a.entity=?"); args.append(entity)
    base = "SELECT a.*, u.email FROM audit_log a LEFT JOIN users u USING (user_id)" + (
        " WHERE " + " AND ".join(where) if where else "")
    page = Page(scalar(f"SELECT COUNT(*) FROM ({base})", args), page_arg(), 40)
    rows = query(f"{base} ORDER BY a.created_at DESC, a.log_id DESC LIMIT ? OFFSET ?", args + [page.per_page, page.offset])
    entities = [r["entity"] for r in query("SELECT DISTINCT entity FROM audit_log ORDER BY entity")]
    return render_template("admin/audit.html", rows=rows, page=page, entity=entity, entities=entities)


# --------------------------------------------------------------------- users: admin accounts & password reset
@bp.route("/users/new-admin", methods=["GET", "POST"])
@admin_only
def new_admin():
    errors, f = Errors(), {}
    if request.method == "POST":
        f["email"] = clean(request.form.get("email"), 120).lower()
        pw = request.form.get("password", "")
        if not valid_email(f["email"]):
            errors.add("email", "err_email")
        elif scalar("SELECT 1 FROM users WHERE email=?", (f["email"],)):
            errors.add("email", "err_email_taken")
        problem = password_problem(pw)
        if problem:
            errors.add("password", problem)
        if not errors:
            uid = execute("INSERT INTO users (email, password_hash, role) VALUES (?,?, 'admin')",
                          (f["email"], generate_password_hash(pw)))
            audit("admin_created", "users", uid)
            flash(_("flash_saved"), "success")
            return redirect(url_for("admin.entity_list", entity="users"))
    return render_template("admin/new_admin.html", f=f, errors=errors)


@bp.route("/users/<int:user_id>/password", methods=["POST"])
@admin_only
def reset_password(user_id):
    pw = request.form.get("password", "")
    problem = password_problem(pw)
    if problem:
        flash(_(problem), "error")
    else:
        execute("UPDATE users SET password_hash=? WHERE user_id=?", (generate_password_hash(pw), user_id))
        audit("password_reset", "users", user_id)
        flash(_("flash_password_changed"), "success")
    return redirect(url_for("admin.entity_edit", entity="users", pk=user_id))


# --------------------------------------------------------------------- generic CRUD
def entity_or_404(entity):
    cfg = ENTITIES.get(entity)
    if not cfg:
        abort(404)
    return cfg


@bp.route("/<entity>")
@admin_only
def entity_list(entity):
    cfg = entity_or_404(entity)
    q = clean(request.args.get("q"), 100)
    where, args = [], []
    if q:
        where.append("(" + " OR ".join(f"{c} LIKE ?" for c in cfg["search"]) + ")")
        args += [f"%{q}%"] * len(cfg["search"])
    active_filters, outer, oargs = {}, [], []
    for col, choices in cfg.get("filters", {}).items():
        val = request.args.get(col, "")
        if val in choices:
            outer.append(f"{col} = ?"); oargs.append(val)
            active_filters[col] = val
    base = cfg["list_sql"] + (" WHERE " + " AND ".join(where) if where else "")
    base = f"SELECT * FROM ({base})" + (" WHERE " + " AND ".join(outer) if outer else "")
    args += oargs
    page = Page(scalar(f"SELECT COUNT(*) FROM ({base})", args), page_arg(), 25)
    rows = query(f"{base} ORDER BY {cfg['pk']} DESC LIMIT ? OFFSET ?", args + [page.per_page, page.offset])
    return render_template("admin/list.html", entity=entity, cfg=cfg, rows=rows, page=page, q=q,
                           active_filters=active_filters)


def fk_options(field):
    table, pk, label = field["ref"]
    return query(f"SELECT {pk} AS id, {label} AS label FROM {table} ORDER BY {label}")


def read_form(cfg):
    values, errors = {}, Errors()
    for fld in cfg["fields"]:
        name, kind = fld["name"], fld["kind"]
        raw = request.form.get(name, "")
        if kind == "bool":
            values[name] = 1 if raw else 0
            continue
        raw = raw.strip()
        if raw == "":
            if fld["required"]:
                errors.add(name, "err_required")
            values[name] = None
            continue
        if kind == "int":
            try:
                values[name] = int(raw)
            except ValueError:
                errors.add(name, "err_number")
        elif kind == "real":
            try:
                values[name] = float(raw.replace(",", "."))
            except ValueError:
                errors.add(name, "err_number")
        elif kind == "fk":
            try:
                values[name] = int(raw)
            except ValueError:
                errors.add(name, "err_required")
        elif kind == "select":
            if raw not in fld["choices"]:
                errors.add(name, "err_required")
            values[name] = raw
        elif kind == "datetime":
            values[name] = raw.replace("T", " ")[:16]
        elif kind == "email":
            if not valid_email(raw):
                errors.add(name, "err_email")
            values[name] = raw.lower()
        else:
            values[name] = raw
    return values, errors


@bp.route("/<entity>/new", methods=["GET", "POST"])
@admin_only
def entity_new(entity):
    cfg = entity_or_404(entity)
    if not cfg.get("create"):
        abort(404)
    values, errors = {}, Errors()
    if request.method == "POST":
        values, errors = read_form(cfg)
        if not errors:
            cols = list(values)
            try:
                new_id = execute(f"INSERT INTO {cfg['table']} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                 [values[c] for c in cols])
                audit("admin_create", cfg["table"], new_id)
                flash(_("flash_saved"), "success")
                return redirect(url_for("admin.entity_list", entity=entity))
            except sqlite3.IntegrityError as e:
                flash(friendly_db_error(e), "error")
    return render_template("admin/form.html", entity=entity, cfg=cfg, row=values, errors=errors, fk_options=fk_options,
                           is_new=True)


@bp.route("/<entity>/<int:pk>", methods=["GET", "POST"])
@admin_only
def entity_edit(entity, pk):
    cfg = entity_or_404(entity)
    row = query(f"SELECT * FROM {cfg['table']} WHERE {cfg['pk']}=?", (pk,), one=True)
    if not row:
        abort(404)
    errors = Errors()
    values = dict(row)
    if request.method == "POST":
        if cfg.get("edit") is False:
            abort(405)
        new_values, errors = read_form(cfg)
        values.update(new_values)
        if entity == "users" and pk == g.user["user_id"] and not new_values.get("is_active"):
            errors.add("is_active", "err_self_block")
        if not errors:
            changes = {k: v for k, v in new_values.items() if row[k] != v}
            if changes:
                try:
                    sets = ", ".join(f"{k}=?" for k in changes)
                    execute(f"UPDATE {cfg['table']} SET {sets} WHERE {cfg['pk']}=?", list(changes.values()) + [pk])
                    for k, v in changes.items():
                        audit("admin_update." + k, cfg["table"], pk, row[k], v)
                    flash(_("flash_saved"), "success")
                    return redirect(url_for("admin.entity_edit", entity=entity, pk=pk))
                except sqlite3.IntegrityError as e:
                    flash(friendly_db_error(e), "error")
            else:
                flash(_("flash_no_changes"), "info")
    related = _related(entity, pk)
    return render_template("admin/form.html", entity=entity, cfg=cfg, row=values, errors=errors,
                           fk_options=fk_options, is_new=False, pk=pk, related=related)


def _related(entity, pk):
    """Small read-only context shown next to the edit form."""
    if entity == "events":
        return dict(kind="registrations", rows=query(
            """SELECT r.registration_id, v.full_name, r.status, r.hours_confirmed FROM registrations r
               JOIN volunteers v USING (volunteer_id) WHERE r.event_id=? ORDER BY r.applied_at""", (pk,)))
    if entity == "volunteers":
        return dict(kind="registrations", rows=query(
            """SELECT r.registration_id, e.title AS full_name, r.status, r.hours_confirmed FROM registrations r
               JOIN events e USING (event_id) WHERE r.volunteer_id=? ORDER BY e.starts_at DESC""", (pk,)))
    if entity == "registrations":
        return dict(kind="audit", rows=query(
            """SELECT a.*, u.email FROM audit_log a LEFT JOIN users u USING (user_id)
               WHERE a.entity='registrations' AND a.entity_id=? ORDER BY a.log_id DESC""", (pk,)))
    return None


@bp.route("/<entity>/<int:pk>/delete", methods=["POST"])
@admin_only
def entity_delete(entity, pk):
    cfg = entity_or_404(entity)
    if entity == "users" and pk == g.user["user_id"]:
        flash(_("err_self_delete"), "error")
        return redirect(url_for("admin.entity_list", entity=entity))
    try:
        with transaction():
            execute(f"DELETE FROM {cfg['table']} WHERE {cfg['pk']}=?", (pk,))
            audit("admin_delete", cfg["table"], pk)
        flash(_("flash_deleted"), "success")
    except sqlite3.IntegrityError as e:
        flash(friendly_db_error(e), "error")
        return redirect(url_for("admin.entity_edit", entity=entity, pk=pk))
    return redirect(url_for("admin.entity_list", entity=entity))
