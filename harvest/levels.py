"""School levels, grades, names and the other facts read from a school's name.

Kenya's Competency-Based Curriculum (CBC) structure, which this directory
files every school under:

    Pre-primary   PP1-PP2      (ECDE centres, nursery, kindergarten)
    Primary       Grades 1-6
    Junior School Grades 7-9   (since 2023 housed mostly in primary schools,
                                 which are then called comprehensive schools)
    Senior School Grades 10-12 (the former secondary schools, Forms 1-4)
    Post-secondary             (TVET, teacher training colleges, universities)
"""

import re

ECDE = 1
PRIMARY = 2
JUNIOR = 4
SENIOR = 8
TVET = 16
TTC = 32
UNIVERSITY = 64
ADULT = 128
NONFORMAL = 256

LEVELS = [
    # bit, key, label, first grade, last grade
    (ECDE, "ecde", "Pre-primary (ECDE)", -1, 0),
    (PRIMARY, "primary", "Primary", 1, 6),
    (JUNIOR, "junior", "Junior School", 7, 9),
    (SENIOR, "senior", "Senior / Secondary", 10, 12),
    (NONFORMAL, "nonformal", "Non-formal (APBET)", 1, 8),
    (TVET, "tvet", "TVET / Polytechnic", 13, 13),
    (TTC, "ttc", "Teacher training college", 13, 13),
    (UNIVERSITY, "university", "University", 13, 13),
    (ADULT, "adult", "Adult education", 13, 13),
]
BY_KEY = {key: bit for bit, key, *_ in LEVELS}
GRADE_LABELS = {-1: "PP1", 0: "PP2", 13: "Post-secondary", **{g: f"Grade {g}" for g in range(1, 13)}}


def grades_for(mask):
    lo = [g0 for bit, _, _, g0, _ in LEVELS if mask & bit]
    hi = [g1 for bit, _, _, _, g1 in LEVELS if mask & bit]
    return (min(lo), max(hi)) if lo else (None, None)


def mask_for_grades(grades, primary_hosts_junior=True):
    """Level bits that teach any of the given grades (-1..13)."""
    mask = 0
    for bit, _, _, g0, g1 in LEVELS:
        if bit in (ADULT,):
            continue
        if any(g0 <= g <= g1 for g in grades):
            mask |= bit
    if primary_hosts_junior and any(7 <= g <= 9 for g in grades):
        mask |= PRIMARY
    return mask


def label_list(mask):
    return [label for bit, _, label, _, _ in LEVELS if mask & bit]


def apply_grades(conn, school_id):
    r = conn.execute("SELECT levels FROM schools WHERE id=?", (school_id,)).fetchone()
    if r:
        lo, hi = grades_for(r["levels"] or 0)
        conn.execute("UPDATE schools SET grade_min=?, grade_max=? WHERE id=?", (lo, hi, school_id))


def apply_all_grades(conn):
    """grade_min / grade_max from the level mask, for every school in one statement."""
    lo = " ".join(f"WHEN levels & {bit} THEN {g0}" for bit, _, _, g0, _ in sorted(LEVELS, key=lambda x: x[3]))
    hi = " ".join(f"WHEN levels & {bit} THEN {g1}" for bit, _, _, _, g1 in sorted(LEVELS, key=lambda x: -x[4]))
    conn.execute(f"UPDATE schools SET grade_min = CASE {lo} ELSE NULL END, grade_max = CASE {hi} ELSE NULL END")


# ------------------------------------------------------------------ Ministry list levels

MOE_LEVEL = [
    (re.compile(r"PRE-?\s?PRIMARY|^ECD|PPRI"), ECDE),
    (re.compile(r"^PRIMARY"), PRIMARY),
    (re.compile(r"^SECONDARY"), SENIOR),
    (re.compile(r"NON[- ]?FORMAL"), NONFORMAL),
    (re.compile(r"ADULT"), ADULT),
    (re.compile(r"POLYTECHNIC|TECHNICAL|INSTITUTE OF TECHNOLOGY"), TVET),
    (re.compile(r"TEACHERS? TRAINING"), TTC),
    (re.compile(r"UNIVERSITY"), UNIVERSITY),
]


def moe_level(level_text, name):
    t = (level_text or "").upper().strip()
    for rx, bit in MOE_LEVEL:
        if rx.search(t):
            return bit
    return levels_from_name(name) or 0


# ------------------------------------------------------------------ names

NAME_LEVEL = [
    (re.compile(r"\bUNIVERSITY\b", re.I), UNIVERSITY),
    (re.compile(r"\bTEACHERS?'?\s*(?:TRAINING\s*)?COLLEGE\b|\bT\.?T\.?C\b", re.I), TTC),
    (re.compile(r"POLYTECHNIC|TECHNICAL|VOCATIONAL|\bT\.?V\.?C\b|\bTVET\b|INSTITUTE OF TECHNOLOGY|"
                r"TRAINING (?:INSTITUTE|CENT(?:RE|ER))|\bCOLLEGE\b|\bINSTITUTE\b", re.I), TVET),
    (re.compile(r"\bADULT\b", re.I), ADULT),
    (re.compile(r"NON[- ]?FORMAL|\bAPBET\b", re.I), NONFORMAL),
    (re.compile(r"\bSEC(?:ONDARY|\.)?\b|\bHIGH\s+SCH|\bHIGH SCHOOL\b|\bHIGH\b|\bSENIOR (?:SCHOOL|SEC)|\bS\.?S\.?$", re.I), SENIOR),
    (re.compile(r"\bJUNIOR (?:SEC(?:ONDARY)?|SCHOOL)\b|\bJ\.?S\.?S\b|\bCOMPREHENSIVE\b", re.I), JUNIOR),
    (re.compile(r"\bPRI(?:MARY|\.)?\b|\bPRY\b|\bCOMPREHENSIVE\b", re.I), PRIMARY),
    (re.compile(r"\bE\.?C\.?D\.?E?\b|\bNUR(?:SERY|\.)?\b|PRE[- ]?(?:SCHOOL|PRIMARY|UNIT)|KINDERGAR?TEN|\bKG\b|"
                r"BABY CLASS|DAY ?CARE|\bPP\s?[12]?\b|MONTESSORI", re.I), ECDE),
]


def levels_from_name(name):
    mask = 0
    for rx, bit in NAME_LEVEL:
        if rx.search(name or ""):
            mask |= bit
    if mask & (TTC | UNIVERSITY):
        mask &= ~TVET
    if mask & SENIOR and re.search(r"\bJUNIOR SEC", name or "", re.I) and not re.search(r"\bSENIOR|\bSEC(?:ONDARY)? SCH", name or "", re.I):
        mask &= ~SENIOR
    if not mask and re.search(r"\bACADEMY\b|\bSCH(?:OOL)?S?\b|\bJUNIOR\b", name or "", re.I):
        mask = PRIMARY  # "Sunrise Academy", "Hilltop Junior" — overwhelmingly primary schools
    return mask


def osm_levels(tags):
    mask = 0
    amenity = tags.get("amenity")
    isced = tags.get("isced:level") or ""
    for part in re.split(r"[;,]", isced):
        part = part.strip()
        m = re.fullmatch(r"(\d)\s*-\s*(\d)", part)
        nums = range(int(m.group(1)), int(m.group(2)) + 1) if m else ([int(part)] if part.isdigit() else [])
        for n in nums:
            mask |= {0: ECDE, 1: PRIMARY, 2: JUNIOR, 3: SENIOR, 4: TVET, 5: TVET}.get(n, UNIVERSITY if n >= 6 else 0)
    if amenity == "kindergarten":
        mask |= ECDE
    elif amenity == "university":
        mask |= UNIVERSITY
    elif amenity == "college" and not mask & (TTC | UNIVERSITY):
        mask |= TTC if re.search(r"teacher", tags.get("name") or "", re.I) else TVET
    from_name = levels_from_name(tags.get("name") or "")
    if not mask:
        mask = from_name
    elif from_name & ECDE and amenity == "school":
        mask |= ECDE
    return mask


ABBREV = [
    (r"\bPRI\.?\s*SCH\.?\b", "Primary School"), (r"\bSEC\.?\s*SCH\.?\b", "Secondary School"),
    (r"\bPRY\.?\s*SCH\.?\b", "Primary School"), (r"\bPRI\b\.?", "Primary"), (r"\bPRY\b\.?", "Primary"),
    (r"\bSEC\b\.?", "Secondary"), (r"\bSCH\b\.?", "School"), (r"\bNUR\b\.?", "Nursery"),
    (r"\bACAD\b\.?", "Academy"), (r"\bSPEC\b\.?", "Special"), (r"\bST\.?(?=\s)", "St."),
    (r"\bMT\.?(?=\s)", "Mt."), (r"\bCTR\b", "Centre"), (r"\bCENTER\b", "Centre"),
]
KEEP_UPPER = {"ACK", "AIC", "PCEA", "SDA", "PAG", "PEFA", "FGCK", "RC", "DEB", "ECD", "ECDE", "CBC", "KAG", "AIPCA",
              "ELCK", "RGC", "ADC", "KCB", "NCCK", "GK", "DC", "CDF", "KDF", "NYS", "TTC", "TVC", "JSS", "II", "III",
              "IV", "KPA", "KPLC", "KAPS", "ABC", "AFC", "ICT", "ITC", "USA", "UK", "PP1", "PP2", "APBET", "CITAM",
              "JCC", "KMTC", "RCEA", "ACC", "AGC", "CCM", "MCK", "EAPC", "AICT", "NEP", "PCMF", "BH", "YMCA",
              "YWCA", "SOS", "JKUAT", "KU", "UON", "KEMU", "MKU", "KCA", "IPC", "LTD"}
SMALL = {"of", "and", "the", "for", "de", "la", "&"}


def display_name(raw):
    """'ST. PATRICK KIMALA PRI SCH' -> 'St. Patrick Kimala Primary School'."""
    s = " ".join((raw or "").replace("_", " ").split())
    if not s:
        return s
    shouty = sum(c.isupper() for c in s) > 0.6 * max(1, sum(c.isalpha() for c in s))
    for pat, rep in ABBREV:
        s = re.sub(pat, rep.upper() if shouty else rep, s, flags=re.I)
    if not shouty:
        return s
    words = []
    for i, w in enumerate(s.split(" ")):
        core = re.sub(r"[^A-Za-z0-9]", "", w).upper()
        if core in KEEP_UPPER or re.fullmatch(r"[A-Z](?:\.[A-Z])+\.?", w):
            words.append(w.upper())
        elif i and w.lower() in SMALL:
            words.append(w.lower())
        else:
            words.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
    out = " ".join(words)
    return re.sub(r"'S\b", "'s", out)


GENERIC = re.compile(
    r"\b(?:PRI(?:MARY)?|PRY|SEC(?:ONDARY)?|SCH(?:OOL)?S?|ECDE?|E\.C\.D\.?E?|NUR(?:SERY)?|PRE[- ]?SCHOOL|"
    r"PRE[- ]?PRIMARY|PRE[- ]?UNIT|KINDERGARTEN|CENT(?:RE|ER)|THE|MIXED|DAY|BOARDING|AND|OF|DEB|"
    r"COMPREHENSIVE|JUNIOR|SENIOR|HIGH|UNIT|CLASS|BABY|PP\d?|COMPLEX|SPECIAL|SECTION|ANNEX)\b\.?",
    re.I)


def base_name(name):
    """The part of a school's name that identifies it, for matching records
    across sources and folding a site's ECD/primary/secondary rows together."""
    s = (name or "").upper().replace("'", "").replace("’", "")
    s = re.sub(r"\bST\.?\s*", "ST ", s)
    s = re.sub(r"\bSAINT\b", "ST", s)
    s = GENERIC.sub(" ", s)
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return " ".join(s.split())


def tokens(name):
    return {t for t in base_name(name).split() if len(t) > 1 and t not in ("ST", "GIRLS", "BOYS", "ACADEMY")}


# ------------------------------------------------------------------ other facts in a name

FAITH_RULES = [
    ("Islamic", r"\bMUSLIM|ISLAMI|MADRAS+A|\bDUKSI\b|\bAL[- ]|MASJID|\bMOSQUE|\bIQRA|\bNOOR|\bTAQWA|\bHIDAYA|\bIMAN\b"),
    ("Catholic", r"CATHOLIC|\bR\.?\s?C\.?\b|\bRCEA|\bOUR LADY|\bMARIST|\bLORETO|\bCONSOLATA|\bMARY IMMACULATE|"
                 r"\bHOLY FAMILY|\bHOLY ROSARY|\bSACRED HEART|\bDON BOSCO|\bCARDINAL"),
    ("Anglican (ACK)", r"\bA\.?C\.?K\.?\b|ANGLICAN|\bC\.?M\.?S\b"),
    ("Africa Inland Church", r"\bA\.?I\.?C\.?\b|AFRICA INLAND"),
    ("Presbyterian (PCEA)", r"\bP\.?C\.?E\.?A\.?\b|PRESBYTERIAN"),
    ("Seventh-day Adventist", r"\bS\.?D\.?A\.?\b|ADVENTIST"),
    ("Methodist", r"METHODIST|\bM\.?C\.?K\.?\b"),
    ("Friends (Quaker)", r"\bFRIENDS\b|QUAKER"),
    ("Pentecostal", r"\bP\.?A\.?G\.?\b|PENTECOST|\bPEFA\b|\bF\.?G\.?C\.?K\b|FULL GOSPEL|\bK\.?A\.?G\.?\b|"
                    r"\bELIM\b|REDEEMED|\bRGC\b|\bDELIVERANCE|\bCITAM"),
    ("Salvation Army", r"SALVATION ARMY|\bS\.?A\.? (?:PRI|SEC|SCH|ECD)"),
    ("Baptist", r"BAPTIST"),
    ("Lutheran", r"LUTHERAN|\bELCK\b"),
    ("Church of God", r"CHURCH OF GOD"),
    ("Hindu", r"HINDU|\bSHREE|\bSWAMINARAYAN|\bARYA\b|\bGURU"),
    ("African Independent", r"\bAIPCA\b|\bA\.?I\.?P\.?C\.?A|\bACC ?& ?S\b|\bLEGIO MARIA|\bNOMIYA"),
    ("Christian (other)", r"CHRISTIAN|GOSPEL|\bCHURCH\b|\bBIBLE|\bJESUS|\bFAITH\b|\bGRACE\b|\bEMMANUEL|\bBETHEL|"
                          r"\bZION\b|\bCALVARY|\bMISSIONARY"),
]
FAITH_RULES = [(label, re.compile(rx, re.I)) for label, rx in FAITH_RULES]
OSM_RELIGION = {"muslim": "Islamic", "hindu": "Hindu"}
OSM_DENOMINATION = {"catholic": "Catholic", "roman_catholic": "Catholic", "anglican": "Anglican (ACK)",
                    "seventh_day_adventist": "Seventh-day Adventist", "methodist": "Methodist",
                    "presbyterian": "Presbyterian (PCEA)", "pentecostal": "Pentecostal", "baptist": "Baptist",
                    "lutheran": "Lutheran", "quaker": "Friends (Quaker)", "salvation_army": "Salvation Army"}


def faith_from_name(name):
    for label, rx in FAITH_RULES:
        if rx.search(name or ""):
            return label
    return None


def gender_from_name(name):
    n = (name or "").upper()
    if re.search(r"\bGIRLS?'?S?\b|\bLADIES\b|\bGIRLS'", n):
        return "girls"
    if re.search(r"\bBOYS?'?S?\b|\bBOYS'", n):
        return "boys"
    if re.search(r"\bMIXED\b", n):
        return "mixed"
    return None


def boarding_from_name(name):
    n = (name or "").upper()
    if re.search(r"\bDAY\s*(?:&|AND)\s*BOARDING\b|\bDAY/BOARDING\b", n):
        return "day_boarding"
    if re.search(r"\bBOARDING\b", n):
        return "boarding"
    if re.search(r"\bDAY (?:SEC|SCH|SCHOOL|PRI|MIXED)", n):
        return "day"
    return None


SPECIAL = re.compile(r"SPECIAL|\bDEAF|\bBLIND|HANDICAP|\bAUTIS|MENTALLY|\bCEREBRAL|\bVISUALLY|HEARING IMPAIR|"
                     r"\bINTEGRATED PROGRAMME|\bSNE\b", re.I)


def special_from_name(name):
    return 1 if SPECIAL.search(name or "") else 0


SPONSOR = [
    (re.compile(r"RELIGIOUS|MISSION|CHURCH", re.I), "religious"),
    (re.compile(r"COMMUNITY|PARENTS|SELF HELP", re.I), "community"),
    (re.compile(r"CENTRAL GOV|DEB|MINISTRY|PRISON|DEFENCE|GOVERNMENT", re.I), "government"),
    (re.compile(r"LOCAL (?:GO?V|GORV|AUTH)|MUNICIPAL|COUNCIL", re.I), "local_authority"),
    (re.compile(r"NGO|CBO|NON[- ]?PROFIT|CHILDREN HOME|SOCIETY", re.I), "ngo"),
    (re.compile(r"PRIVATE|INDIVIDUAL|ORGANI[SZ]ATION|DIRECTOR|ESTATE", re.I), "private"),
    (re.compile(r"UNIVERSITY|\bUON\b", re.I), "university"),
]
SPONSOR_LABEL = {"religious": "Religious organisation", "community": "Community", "government": "Government",
                 "local_authority": "County / local authority", "ngo": "NGO / CBO", "private": "Private owner",
                 "university": "University"}


def sponsor_key(text):
    t = (text or "").strip()
    if len(t) < 3:
        return None
    for rx, key in SPONSOR:
        if rx.search(t):
            return key
    return None
