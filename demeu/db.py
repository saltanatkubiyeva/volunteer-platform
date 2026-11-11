import re
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


def upgrade_db(path, schema_path):
    with open(schema_path, encoding="utf-8") as f:
        schema = f.read()
    conn = sqlite3.connect(path)
    for sql in re.findall(r"CREATE (?:TABLE|INDEX|VIEW) IF NOT EXISTS .*?;", schema, re.S):
        conn.execute(sql)
    reg_cols = [r[1] for r in conn.execute("PRAGMA table_info(registrations)")]
    new_cols = [
        ("is_team_lead", "INTEGER NOT NULL DEFAULT 0 CHECK (is_team_lead IN (0,1))"),
        ("preferred_shift_id", "INTEGER REFERENCES event_shifts(shift_id) ON DELETE SET NULL"),
        ("prefers_all_shifts", "INTEGER NOT NULL DEFAULT 0 CHECK (prefers_all_shifts IN (0,1))"),
        ("shift_id", "INTEGER REFERENCES event_shifts(shift_id) ON DELETE SET NULL"),
        ("all_shifts", "INTEGER NOT NULL DEFAULT 0 CHECK (all_shifts IN (0,1))"),
    ]
    for name, definition in new_cols:
        if name not in reg_cols:
            conn.execute(f"ALTER TABLE registrations ADD COLUMN {name} {definition}")
    cert_cols = [r[1] for r in conn.execute("PRAGMA table_info(certificates)")]
    if "type" not in cert_cols:
        create = re.search(r"CREATE TABLE certificates \(.*?\n\);", schema, re.S).group(0)
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        conn.execute(create.replace("CREATE TABLE certificates", "CREATE TABLE certificates_new", 1))
        conn.execute("""INSERT INTO certificates_new (certificate_id, type, registration_id, code, issued_at)
                        SELECT certificate_id, 'event', registration_id, code, issued_at FROM certificates""")
        conn.execute("DROP TABLE certificates")
        conn.execute("ALTER TABLE certificates_new RENAME TO certificates")
        conn.execute("COMMIT")
    conn.commit()
    conn.close()
