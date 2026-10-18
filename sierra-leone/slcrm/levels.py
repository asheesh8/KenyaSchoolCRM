"""Sierra Leone's school levels, districts and the name rules used to file a school.

Structure (Education Act 2023 / FQSE): pre-primary (ages 3-5), primary Classes 1-6,
junior secondary JSS 1-3, senior secondary SSS 1-3 (some still SSS 1-4), then TVET
and tertiary. Every school carries a bit mask so a combined primary + JSS shows up
under both.
"""

import re

LEVELS = [
    # key, bit, label, short
    ("pre_primary", 1, "Pre-primary (nursery)", "Nursery"),
    ("primary", 2, "Primary (Class 1-6)", "Primary"),
    ("junior_secondary", 4, "Junior secondary (JSS 1-3)", "JSS"),
    ("senior_secondary", 8, "Senior secondary (SSS 1-3)", "SSS"),
    ("tvet", 16, "Technical / vocational", "TVET"),
    ("tertiary", 32, "University / college", "Tertiary"),
    ("admin", 64, "Education office / secretariat", "Office"),
]
BIT = {k: b for k, b, _, _ in LEVELS}
LABEL = {k: lbl for k, _, lbl, _ in LEVELS}
SHORT = {k: s for k, _, _, s in LEVELS}


def mask(keys):
    m = 0
    for k in keys or []:
        m |= BIT.get(k, 0)
    return m


def keys(m):
    return [k for k, b, _, _ in LEVELS if (m or 0) & b]


# District -> province, with the 2024/25 Annual School Census school count (MBSSE,
# 2025 ASC report, table 1-1) so coverage can be shown against the real total.
DISTRICTS = {
    "Western Area Urban": ("Western Area", 1958),
    "Western Area Rural": ("Western Area", 1780),
    "Bombali": ("North", 885),
    "Falaba": ("North", 391),
    "Koinadugu": ("North", 317),
    "Tonkolili": ("North", 923),
    "Kambia": ("North West", 655),
    "Karene": ("North West", 450),
    "Port Loko": ("North West", 969),
    "Bo": ("South", 1132),
    "Bonthe": ("South", 331),
    "Moyamba": ("South", 601),
    "Pujehun": ("South", 392),
    "Kailahun": ("East", 591),
    "Kenema": ("East", 1137),
    "Kono": ("East", 932),
}
PROVINCES = ["Western Area", "North", "North West", "South", "East"]
CENSUS_TOTAL = 13444
CENSUS_BY_LEVEL = {"pre_primary": 2189, "primary": 7643, "junior_secondary": 2456, "senior_secondary": 1156}

# Common spellings, old district names and the main towns of each district.
_ALIASES = {
    "western urban": "Western Area Urban", "western area urban": "Western Area Urban", "freetown": "Western Area Urban",
    "western area": "Western Area Urban", "wau": "Western Area Urban", "western rural": "Western Area Rural",
    "western area rural": "Western Area Rural", "war": "Western Area Rural", "waterloo": "Western Area Rural",
    "hastings": "Western Area Rural", "tombo": "Western Area Rural", "kent": "Western Area Rural",
    "york": "Western Area Rural", "regent": "Western Area Rural", "lakka": "Western Area Rural",
    "goderich": "Western Area Urban", "lumley": "Western Area Urban", "kissy": "Western Area Urban",
    "wellington": "Western Area Urban", "aberdeen": "Western Area Urban", "wilberforce": "Western Area Urban",
    "murray town": "Western Area Urban", "brookfields": "Western Area Urban", "congo cross": "Western Area Urban",
    "makeni": "Bombali", "kabala": "Koinadugu", "mongo": "Falaba", "bendugu": "Falaba",
    "magburaka": "Tonkolili", "mile 91": "Tonkolili", "yele": "Tonkolili", "bumbuna": "Tonkolili",
    "kambia": "Kambia", "rokupr": "Kambia", "kamakwie": "Karene", "kamakwei": "Karene", "batkanu": "Karene",
    "port loko": "Port Loko", "portloko": "Port Loko", "lunsar": "Port Loko", "lungi": "Port Loko",
    "masiaka": "Port Loko", "bo": "Bo", "bo city": "Bo", "njala": "Moyamba", "mattru jong": "Bonthe",
    "bonthe": "Bonthe", "moyamba": "Moyamba", "mano": "Moyamba", "pujehun": "Pujehun", "zimmi": "Pujehun",
    "kenema": "Kenema", "blama": "Kenema", "tongo": "Kenema", "kailahun": "Kailahun", "segbwema": "Kailahun",
    "pendembu": "Kailahun", "daru": "Kailahun", "koidu": "Kono", "koidu town": "Kono", "kono": "Kono",
    "tankoro": "Kono", "yengema": "Kono", "bunumbu": "Kailahun",
}


def canonical_district(value):
    if not value:
        return None
    v = re.sub(r"\s+", " ", str(value)).strip()
    for d in DISTRICTS:
        if v.lower() == d.lower():
            return d
    key = v.lower().replace(" district", "").replace(" city", "").strip()
    return _ALIASES.get(key) or _ALIASES.get(v.lower())


def district_from_text(*texts):
    """Best guess from a town or address. Returns None rather than guess wildly."""
    for t in texts:
        if not t:
            continue
        d = canonical_district(t)
        if d:
            return d
        low = " " + re.sub(r"[^a-z0-9 ]", " ", str(t).lower()) + " "
        for alias, dist in sorted(_ALIASES.items(), key=lambda kv: -len(kv[0])):
            if len(alias) >= 4 and f" {alias} " in low:
                return dist
    return None


def province(district):
    return DISTRICTS.get(district, (None,))[0]


_NAME_RULES = [
    (r"\b(universit|polytechnic|college of medicine|fourah bay|ipam|comahs|njala)", ["tertiary"]),
    (r"\bteachers'? (training )?college\b|\btheological\b|\bseminary\b|\bbible college\b", ["tertiary"]),
    (r"\b(technical|vocational|tvet|skills? (training|centre|center)|institute of|commercial college)", ["tvet"]),
    (r"\b(nursery|pre-?school|kindergarten|kg|day ?care|pre-?primary|montessori)\b", ["pre_primary"]),
    (r"\b(junior secondary|j\.?s\.?s)\b", ["junior_secondary"]),
    (r"\b(senior secondary|s\.?s\.?s|high school|grammar school|secondary school|academy)\b",
     ["junior_secondary", "senior_secondary"]),
    (r"\b(primary|r\.?c\.? school|d\.?e\.?c|preparatory|prep school)\b", ["primary"]),
]


def levels_from_name(name):
    """Levels a school's name implies. Empty when the name says nothing."""
    out = []
    low = (name or "").lower()
    for pat, lv in _NAME_RULES:
        if re.search(pat, low):
            for k in lv:
                if k not in out:
                    out.append(k)
            if lv in (["tertiary"],):
                break
    return out


_FAITH = [
    ("Catholic", r"\b(catholic|r\.?c\.?|st\.? |saint |holy |our lady|christ the king|sacred heart|queen of)"),
    ("Methodist", r"\bmethodist\b"), ("UMC", r"\b(u\.?m\.?c|united methodist|e\.?u\.?b)\b"),
    ("Anglican", r"\b(anglican|annie walsh|bishop crowther|cms)\b"), ("Wesleyan", r"\bwesleyan\b"),
    ("Baptist", r"\bbaptist\b"), ("SDA", r"\b(adventist|s\.?d\.?a)\b"),
    ("Pentecostal", r"\b(pentecostal|assemblies of god|church of god|apostolic)\b"),
    ("Ahmadiyya", r"\bahmadiyya\b"), ("Islamic", r"\b(islamic|muslim|ansarul|madrasa|al-|zainab)\b"),
]


def faith_from_name(name):
    low = (name or "").lower()
    for faith, pat in _FAITH:
        if re.search(pat, low):
            return faith
    return None


def norm_name(name):
    """Key for dedupe: lower case, punctuation and filler words removed."""
    n = (name or "").lower().replace("&", " and ")
    n = re.sub(r"\bst\.?\b", "saint", n)
    n = re.sub(r"\b(r\.?c\.?)\b", "roman catholic", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\b(the|of|school|schools|sec|secondary|primary|junior|senior|high|ltd|limited|sl|sierra leone)\b",
               " ", n)
    return re.sub(r"\s+", " ", n).strip()


_ABBREV = [(r"\bj\.?s\.?s\.?\b", "junior secondary"), (r"\bs\.?s\.?s\.?\b", "senior secondary"),
           (r"\bsec\b|\bseconadry\b|\bsecondry\b", "secondary"), (r"\bpry\b|\bprim\b", "primary"),
           (r"\bd\.?e\.?c\.?\b", "district education committee"), (r"\bu\.?m\.?c\.?\b", "united methodist church"),
           (r"\bacdemy\b", "academy"), (r"\bahamdiyya\b", "ahmadiyya"), (r"\bansural\b", "ansarul")]


def merge_key(name):
    """Stricter key for folding duplicates: level words stay, because a village's primary school and its
    junior secondary school are separate institutions with their own head."""
    n = (name or "").lower().replace("&", " and ")
    n = re.sub(r"\bst\.?\s", "saint ", n)
    n = re.sub(r"\br\.?\s?c\.?\b", "roman catholic", n)
    for pat, rep in _ABBREV:
        n = re.sub(pat, rep, n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\b(the|of|school|schools|ltd|limited|sl|sierra leone)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def place_key(*values):
    for v in values:
        k = re.sub(r"[^a-z0-9]", "", (v or "").lower())
        if k:
            return k
    return ""


def similar(a, b):
    """Token overlap of two names, 0..1."""
    ta, tb = set(merge_key(a).split()), set(merge_key(b).split())
    return len(ta & tb) / max(1, min(len(ta), len(tb))) if ta and tb else 0.0


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def clean_email(e):
    e = (e or "").strip().strip(".,;:<>()[]\"'").replace("mailto:", "")
    e = e.split("?")[0].lower()
    return e if EMAIL_RE.match(e) else None


def clean_phone(p):
    """Sierra Leone numbers to +232 XX XXX XXX. Foreign numbers kept as written."""
    raw = (p or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("232") and len(digits) == 11:
        d = digits[3:]
    elif len(digits) == 9 and digits.startswith("0"):
        d = digits[1:]
    elif len(digits) == 8:
        d = digits
    elif raw.startswith("+") and len(digits) >= 8:
        return "+" + digits
    else:
        return None
    return f"+232 {d[:2]} {d[2:5]} {d[5:]}"
