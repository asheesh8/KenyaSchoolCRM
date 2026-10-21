"""School levels shared by every country, and the name / email rules used to file a school.

Each country keeps its own names for the stages (Kenya's Junior School, Sierra Leone's JSS,
Uganda's O-level), but they all map onto the same seven keys, so one filter works across
the continent. Every school carries a bit mask, so a combined primary + junior school
shows up under both.
"""

import re

LEVELS = [
    # key, bit, generic label
    ("pre_primary", 1, "Nursery / pre-primary"),
    ("primary", 2, "Primary"),
    ("lower_secondary", 4, "Lower secondary"),
    ("upper_secondary", 8, "Upper secondary"),
    ("tvet", 16, "Technical / vocational"),
    ("tertiary", 32, "University / college"),
    ("admin", 64, "Education office"),
]
KEYS = [k for k, _, _ in LEVELS]
BIT = {k: b for k, b, _ in LEVELS}
LABEL = {k: lbl for k, _, lbl in LEVELS}

# Older or country-specific keys still accepted in data files.
ALIASES = {
    "junior_secondary": "lower_secondary", "senior_secondary": "upper_secondary", "o_level": "lower_secondary",
    "a_level": "upper_secondary", "secondary": "lower_secondary", "ecde": "pre_primary", "nursery": "pre_primary",
    "junior": "lower_secondary", "senior": "upper_secondary", "university": "tertiary", "college": "tertiary",
    "ttc": "tertiary", "btvet": "tvet", "nonformal": "primary", "office": "admin",
}


def canonical(key):
    k = str(key or "").strip().lower()
    return k if k in BIT else ALIASES.get(k)


def clean_keys(keys_):
    out = []
    for k in keys_ or []:
        c = canonical(k)
        if c and c not in out:
            out.append(c)
    if "secondary" in [str(k).lower() for k in keys_ or []] and "upper_secondary" not in out:
        out.append("upper_secondary")  # plain "secondary" covers both halves
    return sorted(out, key=lambda k: BIT[k])


def mask(keys_):
    m = 0
    for k in keys_ or []:
        m |= BIT.get(canonical(k) or "", 0)
    return m


def keys(m):
    return [k for k, b, _ in LEVELS if (m or 0) & b]


_NAME_RULES = [
    (r"\b(universit|polytechnic|college of (medicine|health|education|nursing)|school of nursing|"
     r"teachers'? (training )?college|\bp\.?t\.?c\b|\bn\.?t\.?c\b|theological|seminary|bible college)", ["tertiary"]),
    (r"\b(technical|vocational|tvet|btvet|skills? (training|centre|center)|institute of|commercial college)",
     ["tvet"]),
    (r"\b(nursery|pre-?school|kindergarten|kg|day ?care|pre-?primary|montessori|e\.?c\.?d\.?e?)\b", ["pre_primary"]),
    (r"\b(junior secondary|j\.?s\.?s|junior school|comprehensive)\b", ["lower_secondary"]),
    (r"\b(senior secondary|s\.?s\.?s|high school|grammar school|secondary school|sec\.? sch|s\.s\.?$|ss$)\b",
     ["lower_secondary", "upper_secondary"]),
    (r"\b(primary|p/s|p\.s\.?|pry|r\.?c\.? school|d\.?e\.?c|preparatory|prep school)\b", ["primary"]),
]


def levels_from_name(name, extra_rules=()):
    """Levels a school's name implies. Empty when the name says nothing."""
    out = []
    low = (name or "").lower()
    for pat, lv in list(extra_rules) + _NAME_RULES:
        if re.search(pat, low):
            for k in lv:
                if k not in out:
                    out.append(k)
            if lv == ["tertiary"]:
                break
    return sorted(out, key=lambda k: BIT[k])


_FAITH = [
    ("Catholic", r"\b(catholic|r\.?c\.?|st\.? |saint |holy |our lady|christ the king|sacred heart|queen of)"),
    ("Methodist", r"\bmethodist\b"), ("UMC", r"\b(u\.?m\.?c|united methodist|e\.?u\.?b)\b"),
    ("Anglican", r"\b(anglican|a\.?c\.?k\.?|church of uganda|c\.?o\.?u\.?|annie walsh|bishop crowther|cms)\b"),
    ("Wesleyan", r"\bwesleyan\b"), ("Baptist", r"\bbaptist\b"), ("SDA", r"\b(adventist|s\.?d\.?a)\b"),
    ("PCEA", r"\b(p\.?c\.?e\.?a|presbyterian)\b"), ("AIC", r"\b(a\.?i\.?c|africa inland)\b"),
    ("Pentecostal", r"\b(pentecostal|assemblies of god|church of god|apostolic|full gospel)\b"),
    ("Ahmadiyya", r"\bahmadiyya\b"), ("Islamic", r"\b(islamic|muslim|ansarul|madrasa|al-|zainab|uganda muslim)\b"),
]


def faith_from_name(name):
    low = (name or "").lower()
    for faith, pat in _FAITH:
        if re.search(pat, low):
            return faith
    return None


def norm_name(name):
    """Loose key for search and dedupe: lower case, punctuation and filler words removed."""
    n = (name or "").lower().replace("&", " and ")
    n = re.sub(r"\bst\.?\b", "saint", n)
    n = re.sub(r"\b(r\.?c\.?)\b", "roman catholic", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\b(the|of|school|schools|sec|secondary|primary|junior|senior|high|ltd|limited)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def clean_email(e):
    e = (e or "").strip().strip(".,;:<>()[]\"'").replace("mailto:", "")
    e = e.split("?")[0].lower()
    return e if EMAIL_RE.match(e) else None
