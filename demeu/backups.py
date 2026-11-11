import os
import re
import sqlite3
from datetime import datetime

from .db import upgrade_db

KEEP = 10
NAME_RE = re.compile(r"^demeu_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})(?:_([a-z]+\d*))?\.db$")


def backup_dir(db_path):
    path = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
    os.makedirs(path, exist_ok=True)
    return path


def create_backup(db_path, kind="manual", keep_all=False):
    folder = backup_dir(db_path)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    name = f"demeu_{stamp}_{kind}.db"
    target = os.path.join(folder, name)
    n = 1
    while os.path.exists(target):
        n += 1
        name = f"demeu_{stamp}_{kind}{n}.db"
        target = os.path.join(folder, name)
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    ok = dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    dst.close()
    src.close()
    if not ok:
        os.remove(target)
        raise RuntimeError("backup integrity check failed")
    if not keep_all:
        prune(db_path)
    return name


def list_backups(db_path):
    folder = backup_dir(db_path)
    rows = []
    for name in os.listdir(folder):
        m = NAME_RE.match(name)
        if not m:
            continue
        full = os.path.join(folder, name)
        rows.append(dict(name=name, path=full, size=os.path.getsize(full),
                         created=datetime.strptime(m.group(1), "%Y-%m-%d_%H-%M-%S"),
                         kind=re.sub(r"\d+$", "", m.group(2) or "manual")))
    rows.sort(key=lambda r: (r["created"], r["name"]), reverse=True)
    return rows


def prune(db_path):
    for old in list_backups(db_path)[KEEP:]:
        os.remove(old["path"])


def find_backup(db_path, name):
    for b in list_backups(db_path):
        if b["name"] == name:
            return b
    return None


def restore_backup(db_path, name):
    b = find_backup(db_path, name)
    if not b:
        raise FileNotFoundError(name)
    check = sqlite3.connect(b["path"])
    ok = check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    check.close()
    if not ok:
        raise RuntimeError("backup file is damaged")
    safety = create_backup(db_path, "beforerestore", keep_all=True)
    src = sqlite3.connect(b["path"])
    dst = sqlite3.connect(db_path, timeout=10)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    upgrade_db(db_path, os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql"))
    prune(db_path)
    return safety


def daily_backup(db_path):
    today = datetime.now().date()
    if any(b["created"].date() == today for b in list_backups(db_path)):
        return None
    return create_backup(db_path, "auto")
