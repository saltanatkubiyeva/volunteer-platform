"""Input validation shared by all forms. Each check returns a translation key on error."""
import re
from datetime import date, datetime

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def clean(value, max_len=None):
    value = (value or "").strip()
    if max_len:
        value = value[:max_len]
    return value


def normalize_phone(raw):
    """Accepts +7 701 123 45 67, 8 701 1234567, 7011234567 -> +77011234567 (Kazakhstan format)."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] in "78":
        digits = digits[1:]
    if len(digits) == 10 and digits[0] == "7":
        return "+7" + digits
    return None


def valid_email(value):
    return bool(EMAIL_RE.match(value or "")) and len(value) <= 120


def password_problem(pw):
    if len(pw or "") < 8:
        return "err_password_short"
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return "err_password_weak"
    return None


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def parse_local_dt(value):
    """<input type=datetime-local> sends 2026-11-05T10:00"""
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value or "", fmt)
        except ValueError:
            continue
    return None


def age_from(birth):
    today = date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


class Errors(dict):
    """field -> translation key"""

    def add(self, field, key):
        self.setdefault(field, key)
