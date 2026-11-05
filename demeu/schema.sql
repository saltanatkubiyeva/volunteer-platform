PRAGMA foreign_keys = ON;

CREATE TABLE cities (
    city_id     INTEGER PRIMARY KEY,
    name_en     TEXT NOT NULL UNIQUE,
    name_ru     TEXT NOT NULL,
    name_kk     TEXT NOT NULL,
    region_en   TEXT NOT NULL,
    lat         REAL,
    lng         REAL
);

CREATE TABLE directions (
    direction_id INTEGER PRIMARY KEY,
    slug         TEXT NOT NULL UNIQUE,
    name_en      TEXT NOT NULL,
    name_ru      TEXT NOT NULL,
    name_kk      TEXT NOT NULL,
    icon         TEXT NOT NULL DEFAULT 'heart',
    tone         TEXT NOT NULL DEFAULT 'mint'
                 CHECK (tone IN ('mint','sage','butter','sky','rose','lilac'))
);

CREATE TABLE users (
    user_id        INTEGER PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash  TEXT NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('volunteer','coordinator','admin')),
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    preferred_lang TEXT NOT NULL DEFAULT 'en' CHECK (preferred_lang IN ('en','ru','kk')),
    created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    last_login_at  TEXT
);

CREATE TABLE volunteers (
    volunteer_id  INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE RESTRICT,
    full_name     TEXT NOT NULL CHECK (length(trim(full_name)) >= 3),
    phone         TEXT NOT NULL CHECK (phone GLOB '+7[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'),
    birth_date    TEXT NOT NULL,
    city_id       INTEGER NOT NULL REFERENCES cities(city_id) ON DELETE RESTRICT,
    about         TEXT,
    skills        TEXT,
    avatar_path   TEXT,
    is_public     INTEGER NOT NULL DEFAULT 1 CHECK (is_public IN (0,1)),
    show_contacts INTEGER NOT NULL DEFAULT 0 CHECK (show_contacts IN (0,1)),
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE volunteer_directions (
    volunteer_id INTEGER NOT NULL REFERENCES volunteers(volunteer_id) ON DELETE CASCADE,
    direction_id INTEGER NOT NULL REFERENCES directions(direction_id) ON DELETE RESTRICT,
    PRIMARY KEY (volunteer_id, direction_id)
);

CREATE TABLE organizations (
    org_id           INTEGER PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE,
    bin              TEXT NOT NULL UNIQUE CHECK (length(bin) = 12 AND bin NOT GLOB '*[^0-9]*'),
    org_type         TEXT NOT NULL CHECK (org_type IN ('ngo','foundation','initiative','university','government','business')),
    description      TEXT NOT NULL,
    city_id          INTEGER NOT NULL REFERENCES cities(city_id) ON DELETE RESTRICT,
    address          TEXT NOT NULL,
    email            TEXT NOT NULL,
    phone            TEXT NOT NULL,
    website          TEXT,
    logo_path        TEXT,
    founded_year     INTEGER CHECK (founded_year BETWEEN 1950 AND 2100),
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','verified','rejected','suspended')),
    status_comment   TEXT,
    verified_at      TEXT,
    verified_by      INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at       TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE organization_directions (
    org_id       INTEGER NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    direction_id INTEGER NOT NULL REFERENCES directions(direction_id) ON DELETE RESTRICT,
    PRIMARY KEY (org_id, direction_id)
);

CREATE TABLE coordinators (
    coordinator_id INTEGER PRIMARY KEY,
    user_id        INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE RESTRICT,
    org_id         INTEGER NOT NULL REFERENCES organizations(org_id) ON DELETE RESTRICT,
    full_name      TEXT NOT NULL CHECK (length(trim(full_name)) >= 3),
    phone          TEXT NOT NULL,
    position       TEXT,
    is_owner       INTEGER NOT NULL DEFAULT 0 CHECK (is_owner IN (0,1)),
    created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE events (
    event_id              INTEGER PRIMARY KEY,
    org_id                INTEGER NOT NULL REFERENCES organizations(org_id) ON DELETE RESTRICT,
    coordinator_id        INTEGER NOT NULL REFERENCES coordinators(coordinator_id) ON DELETE RESTRICT,
    direction_id          INTEGER NOT NULL REFERENCES directions(direction_id) ON DELETE RESTRICT,
    city_id               INTEGER NOT NULL REFERENCES cities(city_id) ON DELETE RESTRICT,
    title                 TEXT NOT NULL CHECK (length(trim(title)) >= 5),
    summary               TEXT NOT NULL,
    description           TEXT NOT NULL,
    address               TEXT NOT NULL,
    starts_at             TEXT NOT NULL,
    ends_at               TEXT NOT NULL,
    registration_deadline TEXT NOT NULL,
    max_volunteers        INTEGER NOT NULL CHECK (max_volunteers BETWEEN 1 AND 1000),
    min_age               INTEGER NOT NULL DEFAULT 14 CHECK (min_age BETWEEN 14 AND 99),
    requires_approval     INTEGER NOT NULL DEFAULT 1 CHECK (requires_approval IN (0,1)),
    requirements          TEXT,
    provided              TEXT,
    cover_path            TEXT,
    status                TEXT NOT NULL DEFAULT 'published'
                          CHECK (status IN ('draft','published','cancelled','completed')),
    cancel_reason         TEXT,
    created_at            TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at            TEXT,
    CHECK (ends_at > starts_at),
    CHECK (registration_deadline <= starts_at)
);

CREATE TABLE registrations (
    registration_id INTEGER PRIMARY KEY,
    volunteer_id    INTEGER NOT NULL REFERENCES volunteers(volunteer_id) ON DELETE RESTRICT,
    event_id        INTEGER NOT NULL REFERENCES events(event_id) ON DELETE RESTRICT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected','cancelled','attended','no_show')),
    motivation      TEXT,
    applied_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    decided_at      TEXT,
    decided_by      INTEGER REFERENCES coordinators(coordinator_id) ON DELETE SET NULL,
    decision_note   TEXT,
    hours_confirmed REAL CHECK (hours_confirmed IS NULL OR (hours_confirmed > 0 AND hours_confirmed <= 24)),
    confirmed_by    INTEGER REFERENCES coordinators(coordinator_id) ON DELETE SET NULL,
    confirmed_at    TEXT,
    UNIQUE (volunteer_id, event_id),
    CHECK (status <> 'attended' OR hours_confirmed IS NOT NULL)
);

CREATE TABLE feedback (
    feedback_id     INTEGER PRIMARY KEY,
    registration_id INTEGER NOT NULL UNIQUE REFERENCES registrations(registration_id) ON DELETE CASCADE,
    rating          INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment         TEXT,
    is_hidden       INTEGER NOT NULL DEFAULT 0 CHECK (is_hidden IN (0,1)),
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE certificates (
    certificate_id  INTEGER PRIMARY KEY,
    registration_id INTEGER NOT NULL UNIQUE REFERENCES registrations(registration_id) ON DELETE RESTRICT,
    code            TEXT NOT NULL UNIQUE CHECK (length(code) = 10),
    issued_at       TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE consents (
    consent_id    INTEGER PRIMARY KEY,
    volunteer_id  INTEGER NOT NULL REFERENCES volunteers(volunteer_id) ON DELETE CASCADE,
    parent_name   TEXT NOT NULL,
    parent_phone  TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    review_comment TEXT,
    reviewed_by   INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    reviewed_at   TEXT,
    uploaded_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE notifications (
    notification_id INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    params          TEXT NOT NULL DEFAULT '{}',
    link            TEXT,
    is_read         INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0,1)),
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE audit_log (
    log_id     INTEGER PRIMARY KEY,
    user_id    INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    action     TEXT NOT NULL,
    entity     TEXT NOT NULL,
    entity_id  INTEGER,
    old_value  TEXT,
    new_value  TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE offices (
    office_id INTEGER PRIMARY KEY,
    city_id   INTEGER NOT NULL REFERENCES cities(city_id) ON DELETE RESTRICT,
    is_head   INTEGER NOT NULL DEFAULT 0 CHECK (is_head IN (0,1)),
    address   TEXT NOT NULL,
    phone     TEXT NOT NULL,
    email     TEXT NOT NULL,
    hours     TEXT NOT NULL,
    lat       REAL NOT NULL,
    lng       REAL NOT NULL
);

CREATE TABLE contact_messages (
    message_id INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL,
    topic      TEXT NOT NULL CHECK (topic IN ('general','organization','volunteer','technical','partnership')),
    message    TEXT NOT NULL CHECK (length(message) >= 10),
    status     TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','in_progress','closed')),
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX idx_events_city_date   ON events(city_id, starts_at);
CREATE INDEX idx_events_direction   ON events(direction_id);
CREATE INDEX idx_events_org         ON events(org_id);
CREATE INDEX idx_reg_event_status   ON registrations(event_id, status);
CREATE INDEX idx_reg_volunteer      ON registrations(volunteer_id);
CREATE INDEX idx_notif_user_unread  ON notifications(user_id, is_read);
CREATE INDEX idx_audit_entity       ON audit_log(entity, entity_id);
