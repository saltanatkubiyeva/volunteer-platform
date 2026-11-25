import os
import re

from flask import Blueprint, abort, current_app, g, redirect, send_from_directory

from .core import login_required
from .db import query

bp = Blueprint("media", __name__)
PUBLIC_DIRS = {"avatars", "logos", "covers"}


@bp.route("/media/<folder>/<name>")
def public_file(folder, name):
    if folder not in PUBLIC_DIRS:
        abort(404)
    return send_from_directory(os.path.join(current_app.config["UPLOAD_DIR"], folder), name,
                               max_age=86400)


@bp.route("/media/photos/<name>")
def event_photo(name):
    p = query("SELECT * FROM event_photos WHERE file_path=?", ("photos/" + name,), one=True)
    if not p:
        abort(404)
    if p["status"] != "visible":
        if not g.user or (g.user["role"] != "admin" and g.user["user_id"] != p["user_id"]):
            abort(404)
    folder = os.path.join(current_app.config["UPLOAD_DIR"], "photos")
    if not os.path.exists(os.path.join(folder, name)):
        m = re.fullmatch(r"(\d{10,13}-[0-9a-f]{12})\.jpg", name)
        if m:
            return redirect(f"https://images.unsplash.com/photo-{m.group(1)}?auto=format&fit=crop&w=1400&q=72")
        abort(404)
    return send_from_directory(folder, name, max_age=86400)


@bp.route("/consents/<int:consent_id>/file")
@login_required
def consent_file(consent_id):
    c = query("SELECT c.*, v.user_id FROM consents c JOIN volunteers v USING (volunteer_id)"
              " WHERE consent_id = ?", (consent_id,), one=True)
    if not c:
        abort(404)
    if g.user["role"] != "admin" and g.user["user_id"] != c["user_id"]:
        abort(403)
    folder, name = c["file_path"].split("/", 1)
    return send_from_directory(os.path.join(current_app.config["UPLOAD_DIR"], folder), name)


@bp.route("/documents/<int:doc_id>/file")
@login_required
def document_file(doc_id):
    d = query("SELECT vs.*, v.user_id FROM volunteer_skills vs JOIN volunteers v USING (volunteer_id)"
              " WHERE vs.volunteer_skill_id = ?", (doc_id,), one=True)
    if not d:
        abort(404)
    allowed = g.user["role"] == "admin" or g.user["user_id"] == d["user_id"]
    if not allowed and g.user["role"] == "coordinator":
        allowed = bool(query("""SELECT 1 FROM registrations r JOIN events e USING (event_id)
            JOIN event_requirements er ON er.event_id = e.event_id AND er.skill_id = ?
            JOIN coordinators c ON c.org_id = e.org_id AND c.user_id = ?
            WHERE r.volunteer_id = ? AND r.status <> 'cancelled' LIMIT 1""",
                             (d["skill_id"], g.user["user_id"], d["volunteer_id"]), one=True))
    if not allowed:
        abort(403)
    folder, name = d["file_path"].split("/", 1)
    return send_from_directory(os.path.join(current_app.config["UPLOAD_DIR"], folder), name)
