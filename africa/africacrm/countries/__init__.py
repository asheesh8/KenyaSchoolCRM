"""Every country the CRM covers. To add one, write a module like ug.py and list it here."""

from . import ke, sl, ug

COUNTRIES = {m.COUNTRY.code: m.COUNTRY for m in (ke, sl, ug)}
CODES = list(COUNTRIES)


def get(code):
    c = COUNTRIES.get(str(code or "").upper())
    if not c:
        raise ValueError(f"Unknown country {code!r}; known: {', '.join(CODES)}")
    return c


def public():
    return [c.public() for c in COUNTRIES.values()]
