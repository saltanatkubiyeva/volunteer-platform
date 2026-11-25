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


SKILLS = [
    ("driver_license", "Driver's licence (category B)", "Водительские права (категория B)", "Жүргізуші куәлігі (B санаты)", "car", 1),
    ("own_car", "Own car (registration certificate)", "Своя машина (техпаспорт)", "Жеке көлік (техпаспорт)", "car", 0),
]


def upgrade_db(path, schema_path):
    with open(schema_path, encoding="utf-8") as f:
        schema = f.read()
    conn = sqlite3.connect(path)
    later = []
    for sql in re.findall(r"CREATE (?:TABLE|INDEX|VIEW) IF NOT EXISTS .*?;", schema, re.S):
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            later.append(sql)
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
    if "deleted_at" not in [r[1] for r in conn.execute("PRAGMA table_info(users)")]:
        conn.execute("ALTER TABLE users ADD COLUMN deleted_at TEXT")
    ev_cols = [r[1] for r in conn.execute("PRAGMA table_info(events)")]
    if "is_urgent" not in ev_cols:
        conn.execute("ALTER TABLE events ADD COLUMN is_urgent INTEGER NOT NULL DEFAULT 0 CHECK (is_urgent IN (0,1))")
    if "urgent_at" not in ev_cols:
        conn.execute("ALTER TABLE events ADD COLUMN urgent_at TEXT")
    for col in ("lat", "lng"):
        if col not in ev_cols:
            conn.execute(f"ALTER TABLE events ADD COLUMN {col} REAL")
    if "series_id" not in ev_cols:
        conn.execute("ALTER TABLE events ADD COLUMN series_id INTEGER REFERENCES events(event_id) ON DELETE SET NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_series ON events(series_id)")
    for table in ("events", "organizations"):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if "deleted_at" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN deleted_at TEXT")
        if "deleted_by" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN deleted_by INTEGER REFERENCES users(user_id) ON DELETE SET NULL")
    fb_cols = [r[1] for r in conn.execute("PRAGMA table_info(feedback)")]
    for name, definition in (("status", "TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('published','pending','hidden'))"),
                             ("flagged_words", "TEXT"), ("hide_reason", "TEXT"),
                             ("reviewed_by", "INTEGER REFERENCES users(user_id) ON DELETE SET NULL"), ("reviewed_at", "TEXT")):
        if name not in fb_cols:
            conn.execute(f"ALTER TABLE feedback ADD COLUMN {name} {definition}")
            if name == "status":
                conn.execute("UPDATE feedback SET status='hidden' WHERE is_hidden=1")
    vol_cols = [r[1] for r in conn.execute("PRAGMA table_info(volunteers)")]
    for name in ("share_plans", "notify_friend_plans", "notify_friend_achievements"):
        if name not in vol_cols:
            conn.execute(f"ALTER TABLE volunteers ADD COLUMN {name} INTEGER NOT NULL DEFAULT 1 CHECK ({name} IN (0,1))")
    for sql in later:
        conn.execute(sql)
    keep = tuple(sk[0] for sk in SKILLS)
    marks = ",".join("?" * len(keep))
    old = f"SELECT skill_id FROM skills WHERE slug NOT IN ({marks})"
    conn.execute(f"DELETE FROM event_requirements WHERE skill_id IN ({old})", keep)
    conn.execute(f"DELETE FROM volunteer_skills WHERE skill_id IN ({old})", keep)
    conn.execute(f"DELETE FROM skills WHERE slug NOT IN ({marks})", keep)
    if not conn.execute("SELECT 1 FROM skills").fetchone():
        conn.executemany("INSERT INTO skills (slug, name_en, name_ru, name_kk, icon, has_expiry) VALUES (?,?,?,?,?,?)", SKILLS)
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
