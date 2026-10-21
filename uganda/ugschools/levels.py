"""Uganda's school levels, regions and districts, and the name rules used to file a school.

Structure: nursery (baby/middle/top class), primary P1-P7, lower secondary (O-level, S1-S4),
upper secondary (A-level, S5-S6), then BTVET and tertiary. Level keys are the ones the
shared Africa CRM uses for every country.
"""

import re

LEVELS = [
    # key, label, short
    ("pre_primary", "Nursery (baby/middle/top class)", "Nursery"),
    ("primary", "Primary (P1-P7)", "Primary"),
    ("lower_secondary", "O-level (S1-S4)", "O-level"),
    ("upper_secondary", "A-level (S5-S6)", "A-level"),
    ("tvet", "Technical / vocational (BTVET)", "BTVET"),
    ("tertiary", "University / college", "Tertiary"),
    ("admin", "Education office / foundation body", "Office"),
]
ORDER = {k: i for i, (k, *_) in enumerate(LEVELS)}

REGIONS = {
    "Central": "Buikwe Bukomansimbi Butambala Buvuma Gomba Kalangala Kalungu Kampala Kassanda Kayunga Kiboga "
               "Kyankwanzi Kyotera Luwero Lwengo Lyantonde Masaka Mityana Mpigi Mubende Mukono Nakaseke "
               "Nakasongola Rakai Ssembabule Wakiso",
    "Eastern": "Amuria Budaka Bududa Bugiri Bugweri Bukedea Bukwo Bulambuli Busia Butaleja Butebo Buyende Iganga "
               "Jinja Kaberamaido Kalaki Kaliro Kamuli Kapchorwa Kapelebyong Katakwi Kibuku Kumi Kween Luuka "
               "Manafwa Mayuge Mbale Namayingo Namisindwa Namutumba Ngora Pallisa Serere Sironko Soroti Tororo",
    "Northern": "Abim Adjumani Agago Alebtong Amolatar Amudat Amuru Apac Arua Dokolo Gulu Kaabong Karenga Kitgum "
                "Koboko Kole Kotido Kwania Lamwo Lira Madi_Okollo Maracha Moroto Moyo Nabilatuk Nakapiripirit "
                "Napak Nebbi Nwoya Obongi Omoro Otuke Oyam Pader Pakwach Terego Yumbe Zombo",
    "Western": "Buhweju Buliisa Bundibugyo Bunyangabu Bushenyi Hoima Ibanda Isingiro Kabale Kabarole Kagadi "
               "Kakumiro Kamwenge Kanungu Kasese Kazo Kibaale Kikuube Kiruhura Kiryandongo Kisoro Kitagwenda "
               "Kyegegwa Kyenjojo Masindi Mbarara Mitooma Ntoroko Ntungamo Rubanda Rubirizi Rukiga Rukungiri "
               "Rwampara Sheema",
}
DISTRICTS = {d.replace("_", " "): r for r, ds in REGIONS.items() for d in ds.split()}
_BY_LOWER = {d.lower(): d for d in DISTRICTS}

# Old spellings, cities and the main towns and suburbs of each district.
_ALIASES = {
    "luweero": "Luwero", "sembabule": "Ssembabule", "kasanda": "Kassanda", "madi-okollo": "Madi Okollo",
    "madi okolo": "Madi Okollo", "kampala capital city": "Kampala", "kcca": "Kampala", "fort portal": "Kabarole",
    "fortportal": "Kabarole", "entebbe": "Wakiso", "nansana": "Wakiso", "kira": "Wakiso", "kasangati": "Wakiso",
    "gayaza": "Wakiso", "kisubi": "Wakiso", "nabbingo": "Wakiso", "budo": "Wakiso", "kakiri": "Wakiso",
    "matugga": "Wakiso", "kajjansi": "Wakiso", "kitende": "Wakiso", "nkumba": "Wakiso", "namugongo": "Wakiso",
    "kireka": "Wakiso", "bweyogerere": "Wakiso", "kyaliwajjala": "Wakiso", "namasuba": "Wakiso", "lubowa": "Wakiso",
    "buloba": "Wakiso", "nsangi": "Wakiso", "kyengera": "Wakiso", "wakiso": "Wakiso", "najjera": "Wakiso",
    "seeta": "Mukono", "namilyango": "Mukono", "nagalama": "Mukono", "lugazi": "Buikwe", "njeru": "Buikwe",
    "nkokonjeru": "Buikwe", "bombo": "Luwero", "wobulenzi": "Luwero", "kasana": "Luwero", "zirobwe": "Luwero",
    "ndejje": "Luwero", "kayabwe": "Mpigi", "busembatya": "Namutumba", "mwiri": "Jinja", "bugembe": "Jinja",
    "bweyale": "Kiryandongo", "ishaka": "Bushenyi", "kabwohe": "Sheema", "kyotera": "Kyotera", "kalisizo": "Kyotera",
    "villa maria": "Kalungu", "lukaya": "Kalungu", "nyendo": "Masaka", "kitovu": "Masaka", "nyamitanga": "Mbarara",
    "kakoba": "Mbarara", "kamukuzi": "Mbarara", "rushere": "Kiruhura", "bwera": "Kasese", "hima": "Kasese",
    "kigumba": "Kiryandongo", "nyakasura": "Kabarole", "kyegobe": "Kabarole", "aloet": "Soroti", "layibi": "Gulu",
    "laroo": "Gulu", "ngetta": "Lira", "mvara": "Arua", "ombaci": "Arua", "muni": "Arua", "nkozi": "Mpigi",
    "kampala": "Kampala",
}
for _s in ("ntinda nakawa kawempe makindye rubaga lubaga kololo muyenga bugolobi kyambogo nsambya mengo ggaba "
           "kansanga bukoto naguru nakasero kibuli wandegeya makerere mulago munyonyo mutundwe nateete kasubi "
           "bulenga kisaasi kyanja kiwatule kabalagala kibuye katwe kawempe nakulabye kamwokya kisugu kitintale "
           "luzira mbuya mutungo kiwaatule bunga konge lungujja kalerwe bwaise kanyanya komamboga").split():
    _ALIASES[_s] = "Kampala"


def canonical_district(value):
    if not value:
        return None
    v = re.sub(r"\s+", " ", str(value)).strip().lower()
    v = re.sub(r"\b(district|city|municipality|municipal council|local government|dlg)\b", "", v).strip(" ,-")
    return _BY_LOWER.get(v) or _ALIASES.get(v)


def district_from_text(*texts):
    """Best guess from a town or address. Returns None rather than guess wildly."""
    for t in texts:
        if not t:
            continue
        d = canonical_district(t)
        if d:
            return d
        low = " " + re.sub(r"[^a-z0-9 ]", " ", str(t).lower()) + " "
        for alias in sorted(list(_BY_LOWER) + list(_ALIASES), key=len, reverse=True):
            if len(alias) >= 4 and f" {alias} " in low:
                return _BY_LOWER.get(alias) or _ALIASES[alias]
    return None


def region(district):
    return DISTRICTS.get(district)


_TERTIARY = (r"\buniversit|\bteachers?'? (training )?(college|institute)\b|\b(core )?p\.?t\.?c\b|\bprimary teachers\b|\bn\.?t\.?c\b"
             r"|\bnational teachers\b|\bnursing\b|\bmidwi|\bhealth (training|sciences?|institute)\b|\bparamedical\b"
             r"|\bmedical (laboratory|training)\b|\btheolog|\bmajor seminary\b|\bbible (college|institute)\b"
             r"|\b(college|school|institute) of (business|management|accountancy|commerce|health|nursing|law|journalism)\b"
             r"|\bmanagement institute\b|\bcollege of (education|agriculture)\b")
_TVET = (r"\btechnical\b|\bvocational\b|\bpolytechnic\b|\bu\.?t\.?c\b|\bfarm school\b|\bskills?\b"
         r"|\btechnical institute\b|\bhotel and tourism\b|\bdriving school\b|\btailoring\b|\bhair ?dressing\b")
_NAME_RULES = [
    (r"\b(nursery|kindergarten|kinder ?garten|day ?care|pre-?school|e\.?c\.?d\.?|baby care|montessori|n/s)\b"
     r"|\bnur\b|\bnur\.? ?(and|&)", ["pre_primary"]),
    (r"\b(secondary|s\.\s?s\b|ss\b|s/s\b|seed school|comprehensive|o[ -]level)", ["lower_secondary"]),
    (r"\b(high school|a[ -]level|college)\b", ["lower_secondary", "upper_secondary"]),
    (r"\b(primary|p/s|p\.\s?s\b|ps\b|junior school|prep(aratory)? school|boarding primary|demonstration school)",
     ["primary"]),
]


def levels_from_name(name):
    """Levels a school's name implies. Empty when the name says nothing."""
    low = (name or "").lower()
    if re.search(_TERTIARY, low):
        return ["tertiary"]
    if re.search(_TVET, low) and not re.search(r"\b(primary|secondary|nursery)\b", low):
        return ["tvet"]
    out = []
    for pat, lv in _NAME_RULES:
        if re.search(pat, low):
            out += [k for k in lv if k not in out]
    if "upper_secondary" in out and "primary" in out and "secondary" not in low and "high" not in low:
        # "X College School" / "X Junior College" style names that also say primary: a primary school.
        out = [k for k in out if k not in ("lower_secondary", "upper_secondary")]
    return sorted(out, key=ORDER.get)


_FAITH = [
    ("Anglican", r"\b(c/u|c\.o\.u|cou|church of uganda|anglican|bishop'?s?\b)"),
    ("SDA", r"\b(adventist|s\.?d\.?a)\b"),
    ("Islamic", r"\b(islamic|muslim|madras|madrasa|noor|bilal|al[- ]|nurul|umea|tabliq|tabligh|kibuli|mosque)"),
    ("Orthodox", r"\borthodox\b"),
    ("Pentecostal", r"\b(pentecostal|p\.?a\.?g|assemblies of god|born again|full gospel|elim|deliverance)\b"),
    ("Catholic", r"\b(catholic|r/c|r\.c\.|st\.? |saint |holy |our lady|christ the king|sacred heart|immaculate"
                 r"|mt\.? st|mount saint|lubaga|rubaga|kisubi|namagunga|seminary|marian|maria\b)"),
    ("Baptist", r"\bbaptist\b"),
]


def faith_from_name(name):
    low = (name or "").lower() + " "
    for faith, pat in _FAITH:
        if re.search(pat, low):
            return faith
    return None


_ABBREV = [(r"\bs\.\s?s\.?\b|\bs/s\b|\bss\b|\bsss\b|\bsec\b", "secondary"),
           (r"\bp/s\b|\bp\.\s?s\.?\b|\bps\b|\bpry\b|\bprim\b|\bp/sch\b", "primary"),
           (r"\bn/s\b|\bnur\b", "nursery"), (r"\bc/u\b|\bc\.o\.u\.?\b|\bcou\b", "church of uganda"),
           (r"\br/c\b|\br\.c\.?\b", "catholic"), (r"\bmt\.?\s", "mount "), (r"\bst\.?\s", "saint "),
           (r"\bsch\b", "school"), (r"\bjr\b", "junior"), (r"\bp\.t\.c\b|\bptc\b", "primary teachers college"),
           (r"\butc\b", "uganda technical college"), (r"\bseed secondary school\b", "seed school")]


def merge_key(name):
    """Key for folding duplicates. Level words stay: a village's primary and secondary schools are separate
    institutions with their own head teacher."""
    n = (name or "").lower().replace("&", " and ").replace("’", "'")
    n = re.sub(r"\(.*?\)", " ", n)
    for pat, rep in _ABBREV:
        n = re.sub(pat, rep, n)
    n = re.sub(r"'s\b", "s", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\b(the|of|school|schools|ltd|limited|uganda|ug|and)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def norm_name(name):
    """Looser key: level words dropped too."""
    n = merge_key(name)
    n = re.sub(r"\b(secondary|primary|nursery|junior|senior|high|boarding|day|mixed|community|church|catholic)\b",
               " ", n)
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


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")


def clean_email(e):
    e = (e or "").strip().strip(".,;:<>()[]\"'").replace("mailto:", "")
    e = e.split("?")[0].lower()
    return e if EMAIL_RE.match(e) else None


def clean_phone(p):
    """Ugandan numbers to +256 7XX XXX XXX. Foreign numbers in international form are kept as written."""
    raw = (p or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("256") and len(digits) == 12:
        d = digits[3:]
    elif digits.startswith("2560") and len(digits) == 13:
        d = digits[4:]
    elif len(digits) == 10 and digits.startswith("0"):
        d = digits[1:]
    elif len(digits) == 9 and digits[0] in "2347":
        d = digits
    elif raw.startswith("+") and len(digits) >= 8:
        return "+" + digits
    else:
        return None
    if d[0] not in "2347":
        return None
    return f"+256 {d[:3]} {d[3:6]} {d[6:]}"


def is_mobile(phone):
    """A +256 7XX number: reachable on WhatsApp and SMS."""
    return bool(phone) and phone.startswith("+256 7")
