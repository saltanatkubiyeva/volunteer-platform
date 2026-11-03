# DEMEU — volunteer platform of Kazakhstan

A multi-page web information system: volunteers find events and apply, organizations
publish events and confirm volunteer hours, the administrator verifies organizations and
manages all data. Interface in **English, Russian and Kazakh**.

## How to run (Windows / macOS / Linux)

Requires **Python 3.9+**.

```bash
cd demeu
pip install -r requirements.txt      # only Flask
python run.py                        # open http://127.0.0.1:5000
```

On the first start the database `instance/demeu.db` is created with demo data.
To recreate the demo data from scratch: `python seed.py --reset`.
Everything works without internet (fonts and the map are loaded online when available,
otherwise the site uses system fonts and shows office addresses instead of the map).

Tests: `python -m unittest discover tests -v` (16 tests of the main process and the rules).

## Demo accounts (password for all: `Demeu2026!`)

| Email | Role | What to show |
|---|---|---|
| volunteer@demeu.kz | Volunteer Aruzhan Kassymova (id 1024) | cabinet, hours, milestones, certificate DMU7K2Q9XA, applications |
| minor@demeu.kz | Volunteer, 16 y.o. | cannot apply until the parental consent is approved |
| org@demeu.kz | Owner of Green Steppe (verified) | applications, attendance & hours, new event, team, reports, CSV |
| neworg@demeu.kz | Pavlodar Food Share (on review) | can only save drafts until verification |
| admin@demeu.kz | Administrator | queues, CRUD of every table, audit log |

Example from Task 9: registration **5501** = volunteer **1024** (Aruzhan) at event **310** (City Park Clean-up).

## Exam criteria → where it is

| Requirement | Implementation |
|---|---|
| 5+ functionalities | sign-up/login with roles; profiles with photo upload; event catalogue & applications; approval of applications; attendance & confirmed hours; notifications; certificates with public verification; parental consent upload; reviews & ratings; reports & CSV export; organization team management |
| Multilanguage | EN / RU / KZ switch in the header, saved per user; reference data (cities, directions) stored in 3 languages in the DB |
| Search | global search `/search` over events, organizations and volunteers + filters in every catalogue |
| Admin panel | `/admin`: CRUD for 13 tables, organization verification, consent review, user blocking & password reset, messages, audit log; access only for role `admin` |

## Main process

volunteer applies → (auto-approve or coordinator decision) → event happens → coordinator marks
*came / no-show* and hours → hours appear in the profile, reports and certificate → volunteer leaves a review.

Rules enforced by the system:
- only **verified** organizations can publish; events of others are hidden;
- application: before the deadline, age ≥ min age, under 18 only with approved consent,
  no double registration, no time clash with another event, free places left;
- application runs in one transaction with `BEGIN IMMEDIATE` (two people cannot take the last place);
- hours: only after the start, > 0 and ≤ event length (and ≤ 24 in the DB), every change written to `audit_log`;
- an event with registrations cannot be deleted (`ON DELETE RESTRICT`) — it is cancelled, participants are notified;
- volunteer contacts are visible only to coordinators of organizations they applied to (or to everyone if the volunteer allows).

## Security

Password hashing (Werkzeug), CSRF token in every form, role checks on every route, ownership checks
(a coordinator sees only own organization), login lock after 5 failed attempts, file type/size validation
with random names, consent documents not public, parameterised SQL, autoescaped templates, security headers.

## Structure

```
run.py              start the server
seed.py             demo data (dates relative to today)
demeu/
  schema.sql        17 tables with PK, FK, UNIQUE, CHECK
  __init__.py       app factory
  db.py             connection, transactions
  core.py           languages, access control, CSRF, uploads, notifications, audit
  services.py       business rules of the main process
  public.py         public pages, search, reports
  auth.py           sign-up, login, settings, notifications
  volunteer.py      volunteer cabinet
  org.py            organization cabinet
  admin.py          admin panel (generic CRUD)
  tr_*.py           texts in EN / RU / KZ
  templates/, static/
docs/erd.png        ER diagram generated from schema.sql
tests/              automated tests
```
