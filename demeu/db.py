import sqlite3
from flask import current_app, g


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE"], timeout=10,
                               isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def scalar(sql, args=()):
    row = get_db().execute(sql, args).fetchone()
    return row[0] if row else None


def execute(sql, args=()):
    cur = get_db().execute(sql, args)
    return cur.lastrowid


class transaction:

    def __init__(self, immediate=False):
        self.immediate = immediate

    def __enter__(self):
        get_db().execute("BEGIN IMMEDIATE" if self.immediate else "BEGIN")
        return get_db()

    def __exit__(self, exc_type, exc, tb):
        db = get_db()
        if exc_type is None:
            db.execute("COMMIT")
        else:
            db.execute("ROLLBACK")
        return False


def init_db(path, schema_path):
    conn = sqlite3.connect(path)
    with open(schema_path, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
