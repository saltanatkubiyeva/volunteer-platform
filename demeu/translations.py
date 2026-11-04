from .tr_admin import T as _ADMIN
from .tr_app import T as _APP
from .tr_public import T as _PUBLIC
from .tr_copy import T as _COPY

TRANSLATIONS = {}
for _part in (_PUBLIC, _APP, _ADMIN, _COPY):
    for _key, (_en, _ru, _kk) in _part.items():
        TRANSLATIONS[_key] = {"en": _en, "ru": _ru, "kk": _kk}
