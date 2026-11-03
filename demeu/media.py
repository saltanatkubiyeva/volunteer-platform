"""Serving uploaded files. Avatars, logos and covers are public; consent documents
contain personal data of minors and are shown only to their owner and admins."""
import os

from flask import Blueprint, abort, current_app, g, send_from_directory

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
