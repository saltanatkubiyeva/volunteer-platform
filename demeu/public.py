"""Public pages: home, catalogues (events, volunteers, organisations), profiles,
reports, about, contacts, global search, certificate verification."""
from datetime import date, datetime, timedelta

from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, session, url_for)

from . import services as S
from .core import LANGS, Page, _, arg_int, notify, now_str, page_arg, safe_next
from .db import execute, query, scalar
from .forms import Errors, clean, valid_email

bp = Blueprint("public", __name__)


def ref():
    return dict(cities=query("SELECT * FROM cities ORDER BY name_en"),
                directions=query("SELECT * FROM directions ORDER BY direction_id"))


@bp.route("/lang/<code>")
def set_lang(code):
    if code in LANGS:
        session["lang"] = code
        if g.user:
            execute("UPDATE users SET preferred_lang=? WHERE user_id=?", (code, g.user["user_id"]))
    return redirect(safe_next(request.args.get("next")) or url_for("public.home"))


# --------------------------------------------------------------------- home
@bp.route("/")
def home():
    now = now_str()
    featured = query(S.EVENT_SELECT + f""" WHERE {S.PUBLIC_WHERE} AND e.status='published'
                     AND e.registration_deadline >= ? AND (SELECT COUNT(*) FROM registrations r WHERE r.event_id=e.event_id
                     AND r.status IN ('approved','attended')) < e.max_volunteers ORDER BY e.starts_at LIMIT 6""", (now,))
    stats = dict(
        volunteers=scalar("SELECT COUNT(*) FROM volunteers"),
        orgs=scalar("SELECT COUNT(*) FROM organizations WHERE status='verified'"),
        hours=scalar("SELECT COALESCE(SUM(hours_confirmed),0) FROM registrations WHERE status='attended'"),
        events=scalar("SELECT COUNT(*) FROM events WHERE status='completed'"),
        cities=scalar("SELECT COUNT(DISTINCT city_id) FROM events WHERE status IN ('published','completed')"),
        open=scalar(f"SELECT COUNT(*) FROM events e JOIN organizations o USING(org_id) WHERE {S.PUBLIC_WHERE}"
                    " AND e.status='published' AND e.registration_deadline >= ?", (now,)),
    )
    dir_counts = query(f"""SELECT d.*, COUNT(e.event_id) AS n FROM directions d
        LEFT JOIN events e ON e.direction_id=d.direction_id AND e.status='published' AND e.registration_deadline >= ?
        LEFT JOIN organizations o ON o.org_id=e.org_id AND o.status='verified'
        GROUP BY d.direction_id ORDER BY d.direction_id""", (now,))
    top_orgs = query("""SELECT o.*, c.name_en AS city_name_en, c.name_ru AS city_name_ru, c.name_kk AS city_name_kk,
        (SELECT COUNT(*) FROM events e WHERE e.org_id=o.org_id AND e.status IN ('published','completed')) AS n_events
        FROM organizations o JOIN cities c USING (city_id) WHERE o.status='verified'
        ORDER BY n_events DESC LIMIT 4""")
    recent_reviews = query("""SELECT f.*, v.full_name, v.avatar_path, v.is_public, e.title, e.event_id
        FROM feedback f JOIN registrations r USING (registration_id) JOIN volunteers v USING (volunteer_id)
        JOIN events e USING (event_id) WHERE f.is_hidden=0 AND f.rating>=4 AND length(f.comment) > 20
        GROUP BY f.comment ORDER BY f.created_at DESC LIMIT 3""")
    faces = query("SELECT full_name, avatar_path FROM volunteers WHERE is_public=1 ORDER BY created_at DESC LIMIT 3")
    return render_template("public/home.html", featured=featured, stats=stats, dir_counts=dir_counts,
                           top_orgs=top_orgs, reviews=recent_reviews, faces=faces, **ref())


# --------------------------------------------------------------------- events
@bp.route("/events")
def events():
    q = clean(request.args.get("q"), 100)
    city, direction = arg_int("city"), arg_int("direction")
    when = request.args.get("when", "upcoming")
    only_free = request.args.get("free") == "1"
    sort = request.args.get("sort", "soon")
    now = datetime.now()
    where, args = [S.PUBLIC_WHERE], []
    if q:
        where.append("(e.title LIKE ? OR e.summary LIKE ? OR e.description LIKE ? OR o.name LIKE ? OR e.address LIKE ?)")
        args += [f"%{q}%"] * 5
    if city:
        where.append("e.city_id = ?"); args.append(city)
    if direction:
        where.append("e.direction_id = ?"); args.append(direction)
    if when == "past":
        where.append("e.ends_at < ?"); args.append(now_str())
    else:
        where.append("e.status = 'published' AND e.ends_at >= ?"); args.append(now_str())
        if when == "week":
            where.append("e.starts_at <= ?"); args.append((now + timedelta(days=7)).strftime("%Y-%m-%d 23:59"))
        elif when == "weekend":
            sat = now.date() + timedelta(days=(5 - now.weekday()) % 7)
            if now.weekday() == 6:
                sat = now.date() - timedelta(days=1)
            where.append("e.starts_at BETWEEN ? AND ?")
            args += [f"{sat} 00:00", f"{sat + timedelta(days=1)} 23:59"]
        elif when == "month":
            where.append("e.starts_at <= ?"); args.append((now + timedelta(days=30)).strftime("%Y-%m-%d 23:59"))
    if only_free:
        where.append("""(SELECT COUNT(*) FROM registrations r WHERE r.event_id=e.event_id
                         AND r.status IN ('approved','attended')) < e.max_volunteers
                        AND e.registration_deadline >= ?""")
        args.append(now_str())
    order = {"soon": "e.starts_at ASC", "new": "e.created_at DESC",
             "spots": "(e.max_volunteers - taken) DESC"}.get(sort, "e.starts_at ASC")
    if when == "past":
        order = "e.starts_at DESC"
    base = S.EVENT_SELECT + " WHERE " + " AND ".join(where)
    total = scalar(f"SELECT COUNT(*) FROM ({base})", args)
    page = Page(total, page_arg(), 9)
    rows = query(f"{base} ORDER BY {order} LIMIT ? OFFSET ?", args + [page.per_page, page.offset])
    return render_template("public/events.html", events=rows, page=page, q=q, city=city,
                           direction=direction, when=when, only_free=only_free, sort=sort, **ref())


@bp.route("/events/<int:event_id>")
def event_detail(event_id):
    ev = S.get_event(event_id)
    if not ev:
        abort(404)
    own_org = g.coordinator is not None and g.coordinator["org_id"] == ev["org_id"]
    is_admin = g.user is not None and g.user["role"] == "admin"
    if (ev["status"] == "draft" or ev["org_status"] != "verified") and not (own_org or is_admin):
        abort(404)
    my_reg, reason, consent = None, None, None
    if g.volunteer:
        my_reg = query("SELECT * FROM registrations WHERE volunteer_id=? AND event_id=?",
                       (g.volunteer["volunteer_id"], event_id), one=True)
        reason = S.eligibility(g.volunteer, ev)
        consent = S.consent_status(g.volunteer["volunteer_id"])
    participants = query("""SELECT v.volunteer_id, v.full_name, v.avatar_path, v.is_public FROM registrations r
        JOIN volunteers v USING (volunteer_id) WHERE r.event_id=? AND r.status IN ('approved','attended')
        ORDER BY r.applied_at LIMIT 12""", (event_id,))
    coordinator = query("SELECT full_name, position FROM coordinators WHERE coordinator_id=?",
                        (ev["coordinator_id"],), one=True)
    similar = query(S.EVENT_SELECT + f""" WHERE {S.PUBLIC_WHERE} AND e.status='published'
        AND e.event_id<>? AND (e.direction_id=? OR e.city_id=?) AND e.registration_deadline >= ?
        ORDER BY (e.direction_id=?) DESC, e.starts_at LIMIT 3""",
                    (event_id, ev["direction_id"], ev["city_id"], now_str(), ev["direction_id"]))
    reviews = query("""SELECT f.*, v.full_name, v.avatar_path FROM feedback f JOIN registrations r USING (registration_id)
        JOIN volunteers v USING (volunteer_id) WHERE r.event_id=? AND f.is_hidden=0 ORDER BY f.created_at DESC""",
                    (event_id,))
    return render_template("public/event_detail.html", ev=ev, my_reg=my_reg, reason=reason, consent=consent,
                           participants=participants, coordinator=coordinator, similar=similar,
                           reviews=reviews, own_org=own_org,
                           hours=S.duration_hours(ev["starts_at"], ev["ends_at"]))


# --------------------------------------------------------------------- volunteers
VOL_SELECT = """SELECT v.*, c.name_en AS city_name_en, c.name_ru AS city_name_ru, c.name_kk AS city_name_kk,
    COALESCE((SELECT SUM(hours_confirmed) FROM registrations r WHERE r.volunteer_id=v.volunteer_id
              AND r.status='attended'),0) AS hours,
    (SELECT COUNT(*) FROM registrations r WHERE r.volunteer_id=v.volunteer_id AND r.status='attended') AS n_events
    FROM volunteers v JOIN cities c USING (city_id) JOIN users u ON u.user_id=v.user_id"""


def volunteer_directions(ids):
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out = {}
    for r in query(f"""SELECT vd.volunteer_id, d.* FROM volunteer_directions vd JOIN directions d USING (direction_id)
                       WHERE vd.volunteer_id IN ({marks}) ORDER BY d.direction_id""", ids):
        out.setdefault(r["volunteer_id"], []).append(r)
    return out


@bp.route("/volunteers")
def volunteers():
    q = clean(request.args.get("q"), 100)
    city, direction = arg_int("city"), arg_int("direction")
    sort = request.args.get("sort", "hours")
    where, args = ["v.is_public = 1", "u.is_active = 1"], []
    if q:
        where.append("(v.full_name LIKE ? OR v.skills LIKE ? OR v.about LIKE ?)"); args += [f"%{q}%"] * 3
    if city:
        where.append("v.city_id = ?"); args.append(city)
    if direction:
        where.append("EXISTS (SELECT 1 FROM volunteer_directions vd WHERE vd.volunteer_id=v.volunteer_id"
                     " AND vd.direction_id=?)"); args.append(direction)
    base = VOL_SELECT + " WHERE " + " AND ".join(where)
    total = scalar(f"SELECT COUNT(*) FROM ({base})", args)
    page = Page(total, page_arg(), 12)
    order = {"hours": "hours DESC, v.full_name", "new": "v.created_at DESC", "name": "v.full_name"}.get(sort, "hours DESC")
    rows = query(f"{base} ORDER BY {order} LIMIT ? OFFSET ?", args + [page.per_page, page.offset])
    dirs = volunteer_directions([r["volunteer_id"] for r in rows])
    return render_template("public/volunteers.html", volunteers=rows, dirs=dirs, page=page, q=q,
                           city=city, direction=direction, sort=sort, **ref())


def can_see_contacts(v):
    if v["show_contacts"]:
        return True
    if not g.user:
        return False
    if g.user["role"] == "admin" or (g.volunteer and g.volunteer["volunteer_id"] == v["volunteer_id"]):
        return True
    if g.coordinator:
        return bool(scalar("""SELECT 1 FROM registrations r JOIN events e USING (event_id)
                              WHERE r.volunteer_id=? AND e.org_id=? AND r.status <> 'cancelled'""",
                           (v["volunteer_id"], g.coordinator["org_id"])))
    return False


@bp.route("/volunteers/<int:volunteer_id>")
def volunteer_profile(volunteer_id):
    v = query(VOL_SELECT + " WHERE v.volunteer_id=?", (volunteer_id,), one=True)
    if not v:
        abort(404)
    is_self = g.volunteer is not None and g.volunteer["volunteer_id"] == volunteer_id
    if not v["is_public"] and not is_self and not can_see_contacts(v):
        abort(404)
    email = scalar("SELECT email FROM users WHERE user_id=?", (v["user_id"],))
    activity = query("""SELECT r.*, e.title, e.starts_at, e.event_id, o.name AS org_name, o.org_id,
        d.name_en AS dir_name_en, d.name_ru AS dir_name_ru, d.name_kk AS dir_name_kk, d.icon AS dir_icon, d.tone AS dir_tone
        FROM registrations r JOIN events e USING (event_id) JOIN organizations o ON o.org_id=e.org_id
        JOIN directions d ON d.direction_id=e.direction_id
        WHERE r.volunteer_id=? AND r.status='attended' ORDER BY e.starts_at DESC""", (volunteer_id,))
    by_direction = query("""SELECT d.*, SUM(r.hours_confirmed) AS hours FROM registrations r
        JOIN events e USING (event_id) JOIN directions d ON d.direction_id=e.direction_id
        WHERE r.volunteer_id=? AND r.status='attended' GROUP BY d.direction_id ORDER BY hours DESC""",
                         (volunteer_id,))
    return render_template("public/volunteer_profile.html", v=v, email=email, is_self=is_self,
                           show_contacts=can_see_contacts(v), activity=activity, by_direction=by_direction,
                           dirs=volunteer_directions([volunteer_id]).get(volunteer_id, []),
                           stats=S.volunteer_stats(volunteer_id))


# --------------------------------------------------------------------- organisations
ORG_SELECT = """SELECT o.*, c.name_en AS city_name_en, c.name_ru AS city_name_ru, c.name_kk AS city_name_kk,
    (SELECT COUNT(*) FROM events e WHERE e.org_id=o.org_id AND e.status IN ('published','completed')) AS n_events,
    (SELECT COUNT(*) FROM events e WHERE e.org_id=o.org_id AND e.status='published' AND e.ends_at >= datetime('now','localtime')) AS n_open,
    COALESCE((SELECT SUM(r.hours_confirmed) FROM registrations r JOIN events e USING (event_id)
              WHERE e.org_id=o.org_id AND r.status='attended'),0) AS hours
    FROM organizations o JOIN cities c USING (city_id)"""


def org_directions(ids):
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out = {}
    for r in query(f"""SELECT od.org_id, d.* FROM organization_directions od JOIN directions d USING (direction_id)
                       WHERE od.org_id IN ({marks}) ORDER BY d.direction_id""", ids):
        out.setdefault(r["org_id"], []).append(r)
    return out


@bp.route("/organizations")
def organizations():
    q = clean(request.args.get("q"), 100)
    city, direction = arg_int("city"), arg_int("direction")
    org_type = request.args.get("type", "")
    where, args = ["o.status = 'verified'"], []
    if q:
        where.append("(o.name LIKE ? OR o.description LIKE ?)"); args += [f"%{q}%"] * 2
    if city:
        where.append("o.city_id = ?"); args.append(city)
    if direction:
        where.append("EXISTS (SELECT 1 FROM organization_directions od WHERE od.org_id=o.org_id AND od.direction_id=?)")
        args.append(direction)
    if org_type:
        where.append("o.org_type = ?"); args.append(org_type)
    base = ORG_SELECT + " WHERE " + " AND ".join(where)
    total = scalar(f"SELECT COUNT(*) FROM ({base})", args)
    page = Page(total, page_arg(), 12)
    rows = query(f"{base} ORDER BY n_open DESC, hours DESC LIMIT ? OFFSET ?", args + [page.per_page, page.offset])
    return render_template("public/organizations.html", orgs=rows, dirs=org_directions([r["org_id"] for r in rows]),
                           page=page, q=q, city=city, direction=direction, org_type=org_type,
                           org_types=("ngo", "foundation", "initiative", "university", "government", "business"),
                           **ref())


@bp.route("/organizations/<int:org_id>")
def organization_profile(org_id):
    o = query(ORG_SELECT + " WHERE o.org_id=?", (org_id,), one=True)
    if not o:
        abort(404)
    own = g.coordinator is not None and g.coordinator["org_id"] == org_id
    if o["status"] != "verified" and not own and not (g.user and g.user["role"] == "admin"):
        abort(404)
    upcoming = query(S.EVENT_SELECT + " WHERE e.org_id=? AND e.status='published' AND e.ends_at >= ? ORDER BY e.starts_at",
                     (org_id, now_str()))
    past = query(S.EVENT_SELECT + " WHERE e.org_id=? AND e.status IN ('published','completed') AND e.ends_at < ?"
                 " ORDER BY e.starts_at DESC LIMIT 6", (org_id, now_str()))
    reviews = query("""SELECT f.*, v.full_name, v.avatar_path, e.title, e.event_id FROM feedback f
        JOIN registrations r USING (registration_id) JOIN volunteers v USING (volunteer_id) JOIN events e USING (event_id)
        WHERE e.org_id=? AND f.is_hidden=0 ORDER BY f.created_at DESC LIMIT 10""", (org_id,))
    team = query("SELECT full_name, position FROM coordinators WHERE org_id=? ORDER BY is_owner DESC, full_name", (org_id,))
    return render_template("public/organization_profile.html", o=o, upcoming=upcoming, past=past, reviews=reviews,
                           team=team, stats=S.org_stats(org_id), dirs=org_directions([org_id]).get(org_id, []),
                           own=own)


# --------------------------------------------------------------------- reports
@bp.route("/reports")
def reports():
    city = arg_int("city")
    year = arg_int("year") or date.today().year
    cf, cargs = ("AND e.city_id = ?", [city]) if city else ("", [])
    att = f"FROM registrations r JOIN events e USING (event_id) WHERE r.status='attended' {cf}"
    totals = dict(
        hours=scalar(f"SELECT COALESCE(SUM(r.hours_confirmed),0) {att} AND strftime('%Y', e.starts_at)=?",
                     cargs + [str(year)]),
        participations=scalar(f"SELECT COUNT(*) {att} AND strftime('%Y', e.starts_at)=?", cargs + [str(year)]),
        volunteers=scalar(f"SELECT COUNT(DISTINCT r.volunteer_id) {att} AND strftime('%Y', e.starts_at)=?",
                          cargs + [str(year)]),
        events=scalar(f"SELECT COUNT(*) FROM events e WHERE e.status='completed' {cf} AND strftime('%Y', e.starts_at)=?",
                      cargs + [str(year)]),
    )
    marked = query(f"""SELECT SUM(r.status='attended') AS a, SUM(r.status='no_show') AS n FROM registrations r
                       JOIN events e USING (event_id) WHERE strftime('%Y', e.starts_at)=? {cf}""",
                   [str(year)] + cargs, one=True)
    a, n = marked["a"] or 0, marked["n"] or 0
    totals["attendance"] = round(a * 100 / (a + n)) if a + n else None
    monthly = {m: 0 for m in range(1, 13)}
    for r in query(f"""SELECT CAST(strftime('%m', e.starts_at) AS INTEGER) AS m, SUM(r.hours_confirmed) AS h {att}
                       AND strftime('%Y', e.starts_at)=? GROUP BY m""", cargs + [str(year)]):
        monthly[r["m"]] = r["h"] or 0
    by_city = query(f"""SELECT c.*, COALESCE(SUM(r.hours_confirmed),0) AS hours, COUNT(DISTINCT e.event_id) AS n
        FROM cities c JOIN events e ON e.city_id=c.city_id JOIN registrations r ON r.event_id=e.event_id
        WHERE r.status='attended' AND strftime('%Y', e.starts_at)=? {cf}
        GROUP BY c.city_id ORDER BY hours DESC""", [str(year)] + cargs)
    by_direction = query(f"""SELECT d.*, COALESCE(SUM(r.hours_confirmed),0) AS hours, COUNT(DISTINCT e.event_id) AS n
        FROM directions d JOIN events e ON e.direction_id=d.direction_id JOIN registrations r ON r.event_id=e.event_id
        WHERE r.status='attended' AND strftime('%Y', e.starts_at)=? {cf}
        GROUP BY d.direction_id ORDER BY hours DESC""", [str(year)] + cargs)
    top_orgs = query(f"""SELECT o.org_id, o.name, COALESCE(SUM(r.hours_confirmed),0) AS hours,
        COUNT(DISTINCT e.event_id) AS n, COUNT(DISTINCT r.volunteer_id) AS people
        FROM organizations o JOIN events e ON e.org_id=o.org_id JOIN registrations r ON r.event_id=e.event_id
        WHERE r.status='attended' AND strftime('%Y', e.starts_at)=? {cf}
        GROUP BY o.org_id ORDER BY hours DESC LIMIT 5""", [str(year)] + cargs)
    top_vols = query(f"""SELECT v.volunteer_id, v.full_name, v.avatar_path, SUM(r.hours_confirmed) AS hours, COUNT(*) AS n
        FROM volunteers v JOIN registrations r USING (volunteer_id) JOIN events e USING (event_id)
        WHERE r.status='attended' AND v.is_public=1 AND strftime('%Y', e.starts_at)=? {cf}
        GROUP BY v.volunteer_id ORDER BY hours DESC LIMIT 5""", [str(year)] + cargs)
    years = [int(r["y"]) for r in query("SELECT DISTINCT strftime('%Y', starts_at) AS y FROM events ORDER BY y DESC")]
    return render_template("public/reports.html", totals=totals, monthly=monthly, by_city=by_city,
                           by_direction=by_direction, top_orgs=top_orgs, top_vols=top_vols, city=city,
                           year=year, years=years or [year], **ref())


# --------------------------------------------------------------------- about & contacts
@bp.route("/about")
def about():
    stats = dict(volunteers=scalar("SELECT COUNT(*) FROM volunteers"),
                 orgs=scalar("SELECT COUNT(*) FROM organizations WHERE status='verified'"),
                 hours=scalar("SELECT COALESCE(SUM(hours_confirmed),0) FROM registrations WHERE status='attended'"))
    return render_template("public/about.html", stats=stats)


@bp.route("/contacts", methods=["GET", "POST"])
def contacts():
    offices = query("""SELECT o.*, c.name_en AS city_name_en, c.name_ru AS city_name_ru, c.name_kk AS city_name_kk
                       FROM offices o JOIN cities c USING (city_id) ORDER BY o.is_head DESC, c.name_en""")
    f, errors = {}, Errors()
    if g.user and request.method == "GET":
        f["email"] = g.user["email"]
        person = g.volunteer or g.coordinator
        f["name"] = person["full_name"] if person else ""
    if request.method == "POST":
        f = {k: clean(request.form.get(k), 3000 if k == "message" else 120) for k in ("name", "email", "topic", "message")}
        if request.form.get("website"):  # honeypot field, invisible to people
            return redirect(url_for("public.contacts"))
        if len(f["name"]) < 2:
            errors.add("name", "err_required")
        if not valid_email(f["email"]):
            errors.add("email", "err_email")
        if f["topic"] not in ("general", "organization", "volunteer", "technical", "partnership"):
            errors.add("topic", "err_required")
        if len(f["message"]) < 10:
            errors.add("message", "err_message_short")
        if not errors:
            execute("INSERT INTO contact_messages (name, email, topic, message) VALUES (?,?,?,?)",
                    (f["name"], f["email"], f["topic"], f["message"]))
            for admin in query("SELECT user_id FROM users WHERE role='admin' AND is_active=1"):
                notify(admin["user_id"], "n_admin_new_message", url_for("admin.messages"), name=f["name"])
            flash(_("flash_message_sent"), "success")
            return redirect(url_for("public.contacts"))
    return render_template("public/contacts.html", offices=offices, f=f, errors=errors)


# --------------------------------------------------------------------- search & verification
@bp.route("/search")
def search():
    q = clean(request.args.get("q"), 100)
    tab = request.args.get("tab", "all")
    res = dict(events=[], orgs=[], volunteers=[])
    if len(q) >= 2:
        like = f"%{q}%"
        res["events"] = query(S.EVENT_SELECT + f""" WHERE {S.PUBLIC_WHERE}
            AND (e.title LIKE ? OR e.summary LIKE ? OR e.description LIKE ? OR e.address LIKE ?)
            ORDER BY (e.ends_at >= ?) DESC, e.starts_at LIMIT 30""", (like, like, like, like, now_str()))
        res["orgs"] = query(ORG_SELECT + " WHERE o.status='verified' AND (o.name LIKE ? OR o.description LIKE ?)"
                            " ORDER BY o.name LIMIT 30", (like, like))
        res["volunteers"] = query(VOL_SELECT + """ WHERE v.is_public=1 AND u.is_active=1
            AND (v.full_name LIKE ? OR v.skills LIKE ? OR v.about LIKE ?) ORDER BY hours DESC LIMIT 30""",
                                  (like, like, like))
    vdirs = volunteer_directions([v["volunteer_id"] for v in res["volunteers"]])
    odirs = org_directions([o["org_id"] for o in res["orgs"]])
    return render_template("public/search.html", q=q, tab=tab, res=res, dirs=vdirs, odirs=odirs)


@bp.route("/verify", methods=["GET"])
def verify():
    code = clean(request.args.get("code"), 20).upper()
    cert = None
    if code:
        cert = query("""SELECT ce.*, r.hours_confirmed, v.full_name, e.title, e.starts_at, o.name AS org_name
            FROM certificates ce JOIN registrations r USING (registration_id) JOIN volunteers v USING (volunteer_id)
            JOIN events e USING (event_id) JOIN organizations o ON o.org_id=e.org_id
            WHERE ce.code=? AND r.status='attended'""", (code,), one=True)
    return render_template("public/verify.html", code=code, cert=cert)
