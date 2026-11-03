"""All interface texts in English, Russian and Kazakh.
Every entry is key -> {"en": ..., "ru": ..., "kk": ...}."""
from .tr_admin import T as _ADMIN
from .tr_app import T as _APP
from .tr_public import T as _PUBLIC

TRANSLATIONS = {}
for _part in (_PUBLIC, _APP, _ADMIN):
    for _key, (_en, _ru, _kk) in _part.items():
        TRANSLATIONS[_key] = {"en": _en, "ru": _ru, "kk": _kk}
