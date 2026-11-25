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
    last_login_at  TEXT,
    deleted_at     TEXT,
    CHECK (deleted_at IS NULL OR is_active = 0)
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
    share_plans   INTEGER NOT NULL DEFAULT 1 CHECK (share_plans IN (0,1)),
    notify_friend_plans INTEGER NOT NULL DEFAULT 1 CHECK (notify_friend_plans IN (0,1)),
    notify_friend_achievements INTEGER NOT NULL DEFAULT 1 CHECK (notify_friend_achievements IN (0,1)),
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
    deleted_at       TEXT,
    deleted_by       INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
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
    is_urgent             INTEGER NOT NULL DEFAULT 0 CHECK (is_urgent IN (0,1)),
    urgent_at             TEXT,
    lat                   REAL CHECK (lat IS NULL OR lat BETWEEN -90 AND 90),
    lng                   REAL CHECK (lng IS NULL OR lng BETWEEN -180 AND 180),
    series_id             INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    deleted_at            TEXT,
    deleted_by            INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at            TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at            TEXT,
    CHECK (ends_at > starts_at),
    CHECK ((lat IS NULL) = (lng IS NULL)),
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
    is_team_lead    INTEGER NOT NULL DEFAULT 0 CHECK (is_team_lead IN (0,1)),
    preferred_shift_id INTEGER REFERENCES event_shifts(shift_id) ON DELETE SET NULL,
    prefers_all_shifts INTEGER NOT NULL DEFAULT 0 CHECK (prefers_all_shifts IN (0,1)),
    shift_id        INTEGER REFERENCES event_shifts(shift_id) ON DELETE SET NULL,
    all_shifts      INTEGER NOT NULL DEFAULT 0 CHECK (all_shifts IN (0,1)),
    UNIQUE (volunteer_id, event_id),
    CHECK (status <> 'attended' OR hours_confirmed IS NOT NULL)
);

CREATE TABLE feedback (
    feedback_id     INTEGER PRIMARY KEY,
    registration_id INTEGER NOT NULL UNIQUE REFERENCES registrations(registration_id) ON DELETE CASCADE,
    rating          INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment         TEXT,
    is_hidden       INTEGER NOT NULL DEFAULT 0 CHECK (is_hidden IN (0,1)),
    status          TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('published','pending','hidden')),
    flagged_words   TEXT,
    hide_reason     TEXT,
    reviewed_by     INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    reviewed_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    CHECK ((status = 'published') = (is_hidden = 0))
);

CREATE TABLE certificates (
    certificate_id  INTEGER PRIMARY KEY,
    type            TEXT NOT NULL DEFAULT 'event' CHECK (type IN ('event','milestone')),
    registration_id INTEGER UNIQUE REFERENCES registrations(registration_id) ON DELETE RESTRICT,
    volunteer_id    INTEGER REFERENCES volunteers(volunteer_id) ON DELETE RESTRICT,
    milestone_hours INTEGER CHECK (milestone_hours IN (20, 50, 100)),
    code            TEXT NOT NULL UNIQUE CHECK (length(code) = 10),
    issued_at       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (volunteer_id, milestone_hours),
    CHECK ((type = 'event' AND registration_id IS NOT NULL AND milestone_hours IS NULL)
        OR (type = 'milestone' AND registration_id IS NULL AND volunteer_id IS NOT NULL AND milestone_hours IS NOT NULL))
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

CREATE TABLE IF NOT EXISTS event_shifts (
    shift_id       INTEGER PRIMARY KEY,
    event_id       INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    title          TEXT NOT NULL CHECK (length(title) BETWEEN 2 AND 80),
    starts_at      TEXT NOT NULL,
    ends_at        TEXT NOT NULL,
    max_volunteers INTEGER NOT NULL CHECK (max_volunteers BETWEEN 1 AND 1000),
    position       INTEGER NOT NULL DEFAULT 0,
    UNIQUE (event_id, title),
    CHECK (ends_at > starts_at)
);
CREATE INDEX IF NOT EXISTS idx_shifts_event ON event_shifts(event_id, position);

CREATE TABLE IF NOT EXISTS password_resets (
    reset_id     INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    token_hash   TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    expires_at   TEXT NOT NULL,
    used_at      TEXT,
    requested_by INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    CHECK (expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS idx_resets_user ON password_resets(user_id, created_at);

CREATE TABLE IF NOT EXISTS outbox (
    message_id INTEGER PRIMARY KEY,
    user_id    INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    to_email   TEXT NOT NULL,
    subject    TEXT NOT NULL,
    body       TEXT NOT NULL,
    link       TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS complaints (
    complaint_id INTEGER PRIMARY KEY,
    reporter_id  INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    event_id     INTEGER REFERENCES events(event_id) ON DELETE CASCADE,
    org_id       INTEGER REFERENCES organizations(org_id) ON DELETE CASCADE,
    reason       TEXT NOT NULL CHECK (reason IN ('fake','unsafe','inappropriate','fraud','other')),
    details      TEXT,
    status       TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','resolved','dismissed')),
    action       TEXT CHECK (action IN ('none','event_cancelled','org_suspended','account_blocked')),
    admin_note   TEXT,
    handled_by   INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    handled_at   TEXT,
    CHECK ((event_id IS NULL) <> (org_id IS NULL)),
    CHECK (status = 'new' OR handled_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status, created_at);

CREATE TABLE IF NOT EXISTS skills (
    skill_id    INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name_en     TEXT NOT NULL,
    name_ru     TEXT NOT NULL,
    name_kk     TEXT NOT NULL,
    icon        TEXT NOT NULL DEFAULT 'file-text',
    has_expiry  INTEGER NOT NULL DEFAULT 1 CHECK (has_expiry IN (0,1))
);

CREATE TABLE IF NOT EXISTS volunteer_skills (
    volunteer_skill_id INTEGER PRIMARY KEY,
    volunteer_id   INTEGER NOT NULL REFERENCES volunteers(volunteer_id) ON DELETE CASCADE,
    skill_id       INTEGER NOT NULL REFERENCES skills(skill_id) ON DELETE RESTRICT,
    file_path      TEXT NOT NULL,
    expires_at     TEXT,
    status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    review_comment TEXT,
    reviewed_by    INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    reviewed_at    TEXT,
    uploaded_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (volunteer_id, skill_id),
    CHECK (status = 'pending' OR reviewed_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_vskills_status ON volunteer_skills(status, uploaded_at);

CREATE TABLE IF NOT EXISTS event_requirements (
    event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(skill_id) ON DELETE RESTRICT,
    PRIMARY KEY (event_id, skill_id)
);

CREATE TABLE IF NOT EXISTS waitlist (
    waitlist_id  INTEGER PRIMARY KEY,
    volunteer_id INTEGER NOT NULL REFERENCES volunteers(volunteer_id) ON DELETE CASCADE,
    event_id     INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    motivation   TEXT,
    joined_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (volunteer_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_waitlist_event ON waitlist(event_id, joined_at);

CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id INTEGER PRIMARY KEY,
    volunteer_id    INTEGER NOT NULL REFERENCES volunteers(volunteer_id) ON DELETE CASCADE,
    city_id         INTEGER REFERENCES cities(city_id) ON DELETE CASCADE,
    direction_id    INTEGER REFERENCES directions(direction_id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    CHECK ((city_id IS NULL) <> (direction_id IS NULL)),
    UNIQUE (volunteer_id, city_id, direction_id)
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_volunteer ON subscriptions(volunteer_id);

CREATE VIEW IF NOT EXISTS volunteer_reliability AS
SELECT v.volunteer_id,
       COALESCE(SUM(r.status = 'attended'), 0) AS attended,
       COALESCE(SUM(r.status = 'no_show'), 0)  AS no_show,
       CAST(ROUND(100.0 * SUM(r.status = 'attended') / NULLIF(SUM(r.status IN ('attended','no_show')), 0)) AS INTEGER)
                                                AS attendance_rate
FROM volunteers v
LEFT JOIN registrations r ON r.volunteer_id = v.volunteer_id
GROUP BY v.volunteer_id;

CREATE TABLE IF NOT EXISTS announcements (
    announcement_id INTEGER PRIMARY KEY,
    text_en         TEXT NOT NULL CHECK (length(trim(text_en)) >= 5),
    text_ru         TEXT NOT NULL CHECK (length(trim(text_ru)) >= 5),
    text_kk         TEXT NOT NULL CHECK (length(trim(text_kk)) >= 5),
    tone            TEXT NOT NULL DEFAULT 'info' CHECK (tone IN ('info','warning')),
    audience        TEXT NOT NULL DEFAULT 'all' CHECK (audience IN ('all','volunteers','coordinators','city')),
    city_id         INTEGER REFERENCES cities(city_id) ON DELETE CASCADE,
    link            TEXT,
    starts_at       TEXT NOT NULL,
    ends_at         TEXT NOT NULL,
    notified        INTEGER NOT NULL DEFAULT 0 CHECK (notified IN (0,1)),
    created_by      INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    CHECK (ends_at > starts_at),
    CHECK ((audience = 'city') = (city_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_announcements_dates ON announcements(starts_at, ends_at);

CREATE TABLE IF NOT EXISTS announcement_hidden (
    user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    announcement_id INTEGER NOT NULL REFERENCES announcements(announcement_id) ON DELETE CASCADE,
    hidden_at       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (user_id, announcement_id)
);

CREATE TABLE IF NOT EXISTS event_photos (
    photo_id     INTEGER PRIMARY KEY,
    event_id     INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    user_id      INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    file_path    TEXT NOT NULL UNIQUE,
    status       TEXT NOT NULL DEFAULT 'visible' CHECK (status IN ('visible','hidden')),
    hide_reason  TEXT CHECK (hide_reason IN ('children','ads','unrelated','quality','other')),
    reviewed_by  INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    reviewed_at  TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    CHECK (status = 'visible' OR (hide_reason IS NOT NULL AND reviewed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_photos_event ON event_photos(event_id, status);
CREATE INDEX IF NOT EXISTS idx_photos_review ON event_photos(reviewed_at);

CREATE TABLE IF NOT EXISTS photo_reports (
    report_id   INTEGER PRIMARY KEY,
    photo_id    INTEGER NOT NULL REFERENCES event_photos(photo_id) ON DELETE CASCADE,
    reporter_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    reason      TEXT NOT NULL CHECK (reason IN ('fake','unsafe','inappropriate','fraud','other')),
    details     TEXT,
    status      TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','resolved','dismissed')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    handled_at  TEXT,
    UNIQUE (photo_id, reporter_id),
    CHECK (status = 'new' OR handled_at IS NOT NULL)
);

CREATE INDEX idx_events_series ON events(series_id);

CREATE TABLE IF NOT EXISTS volunteer_feedback (
    feedback_id        INTEGER PRIMARY KEY,
    registration_id    INTEGER NOT NULL UNIQUE REFERENCES registrations(registration_id) ON DELETE CASCADE,
    coordinator_id     INTEGER REFERENCES coordinators(coordinator_id) ON DELETE SET NULL,
    is_thanks          INTEGER NOT NULL DEFAULT 0 CHECK (is_thanks IN (0,1)),
    is_reliable        INTEGER NOT NULL DEFAULT 0 CHECK (is_reliable IN (0,1)),
    good_with_children INTEGER NOT NULL DEFAULT 0 CHECK (good_with_children IN (0,1)),
    comment            TEXT CHECK (comment IS NULL OR length(comment) <= 300),
    created_at         TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at         TEXT,
    CHECK (is_thanks + is_reliable + good_with_children > 0 OR comment IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_events_deleted ON events(deleted_at);
CREATE INDEX IF NOT EXISTS idx_orgs_deleted ON organizations(deleted_at);

CREATE VIEW IF NOT EXISTS trash_items AS
SELECT 'event' AS kind, e.event_id AS item_id, e.title AS name, o.name AS org_name, e.org_id,
       e.status, e.deleted_at, e.deleted_by
FROM events e JOIN organizations o ON o.org_id = e.org_id
WHERE e.deleted_at IS NOT NULL
UNION ALL
SELECT 'organization', o.org_id, o.name, o.name, o.org_id, o.status, o.deleted_at, o.deleted_by
FROM organizations o
WHERE o.deleted_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS banned_words (
    word_id    INTEGER PRIMARY KEY,
    word       TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(word)) >= 3),
    created_by INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS review_reports (
    report_id   INTEGER PRIMARY KEY,
    feedback_id INTEGER NOT NULL REFERENCES feedback(feedback_id) ON DELETE CASCADE,
    reporter_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    reason      TEXT NOT NULL CHECK (reason IN ('offensive','spam','personal','fake','other')),
    details     TEXT,
    status      TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','resolved','dismissed')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    handled_at  TEXT,
    UNIQUE (feedback_id, reporter_id),
    CHECK (status = 'new' OR handled_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_review_reports ON review_reports(feedback_id, status);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status);

CREATE TABLE IF NOT EXISTS blocks (
    block_id   INTEGER PRIMARY KEY,
    user_id    INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
    org_id     INTEGER REFERENCES organizations(org_id) ON DELETE CASCADE,
    reason     TEXT NOT NULL CHECK (length(trim(reason)) >= 5),
    starts_at  TEXT NOT NULL,
    ends_at    TEXT,
    blocked_by INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    lifted_at  TEXT,
    lifted_by  INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    CHECK ((user_id IS NULL) <> (org_id IS NULL)),
    CHECK (ends_at IS NULL OR ends_at > starts_at),
    CHECK (lifted_by IS NULL OR lifted_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_blocks_user ON blocks(user_id, lifted_at, ends_at);
CREATE INDEX IF NOT EXISTS idx_blocks_org ON blocks(org_id, lifted_at);

CREATE TABLE IF NOT EXISTS deed_requests (
    request_id     INTEGER PRIMARY KEY,
    title          TEXT NOT NULL CHECK (length(trim(title)) >= 5),
    description    TEXT NOT NULL CHECK (length(trim(description)) >= 20),
    direction_id   INTEGER NOT NULL REFERENCES directions(direction_id) ON DELETE RESTRICT,
    city_id        INTEGER NOT NULL REFERENCES cities(city_id) ON DELETE RESTRICT,
    area           TEXT NOT NULL,
    when_kind      TEXT NOT NULL CHECK (when_kind IN ('on','by','any')),
    when_date      TEXT,
    people_needed  INTEGER CHECK (people_needed IS NULL OR people_needed BETWEEN 1 AND 200),
    contact_name   TEXT NOT NULL CHECK (length(trim(contact_name)) >= 2),
    contact_email  TEXT NOT NULL,
    contact_phone  TEXT,
    user_id        INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    token_hash     TEXT NOT NULL UNIQUE,
    status         TEXT NOT NULL DEFAULT 'unconfirmed'
                   CHECK (status IN ('unconfirmed','pending','open','taken','done','rejected','expired','withdrawn')),
    reject_reason  TEXT,
    reviewed_by    INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    reviewed_at    TEXT,
    taken_org_id   INTEGER REFERENCES organizations(org_id) ON DELETE SET NULL,
    taken_by       INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    taken_at       TEXT,
    event_id       INTEGER REFERENCES events(event_id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    confirmed_at   TEXT,
    closed_at      TEXT,
    CHECK ((when_kind = 'any') = (when_date IS NULL)),
    CHECK (status <> 'taken' OR (taken_org_id IS NOT NULL AND taken_at IS NOT NULL)),
    CHECK (status <> 'rejected' OR reject_reason IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_deeds_status ON deed_requests(status, city_id);
CREATE INDEX IF NOT EXISTS idx_deeds_org ON deed_requests(taken_org_id, status);

CREATE TABLE IF NOT EXISTS friendships (
    friendship_id INTEGER PRIMARY KEY,
    requester_id  INTEGER NOT NULL REFERENCES volunteers(volunteer_id) ON DELETE CASCADE,
    addressee_id  INTEGER NOT NULL REFERENCES volunteers(volunteer_id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted')),
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    accepted_at   TEXT,
    CHECK (requester_id <> addressee_id),
    CHECK (status = 'pending' OR accepted_at IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_friend_pair ON friendships(min(requester_id, addressee_id), max(requester_id, addressee_id));
CREATE INDEX IF NOT EXISTS idx_friend_addressee ON friendships(addressee_id, status);

CREATE TABLE IF NOT EXISTS kudos (
    kudos_id     INTEGER PRIMARY KEY,
    from_id      INTEGER NOT NULL REFERENCES volunteers(volunteer_id) ON DELETE CASCADE,
    to_id        INTEGER NOT NULL REFERENCES volunteers(volunteer_id) ON DELETE CASCADE,
    milestone    INTEGER NOT NULL CHECK (milestone IN (20, 50, 100, 200)),
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (from_id, to_id, milestone),
    CHECK (from_id <> to_id)
);
