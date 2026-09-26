"""Pull contact details out of a school web page."""

import html as htmllib
import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urljoin, urlsplit




class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []          # (href, text)
        self.text = []
        self.title = ""
        self.description = ""
        self.cf_emails = []
        self.ld_json = []
        self.forms = []
        self._form = None
        self._skip = 0
        self._in_title = False
        self._in_ld = False
        self._ld_buf = []
        self._a_stack = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "svg", "template"):
            if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
                self._in_ld = True
                self._ld_buf = []
            else:
                self._skip += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name in ("description", "og:description") and not self.description:
                self.description = (a.get("content") or "").strip()[:400]
        elif tag == "a":
            self._a_stack.append([a.get("href") or "", []])
        elif tag == "form":
            self._form = {"action": a.get("action") or "", "fields": set()}
        elif tag in ("input", "textarea") and self._form is not None:
            self._form["fields"].add(((a.get("type") or ("textarea" if tag == "textarea" else ""))
                                      + " " + (a.get("name") or "")).lower())
        elif tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "footer", "td"):
            self.text.append("\n")
        cf = a.get("data-cfemail")
        if cf:
            self.cf_emails.append(cf)
        href = a.get("href") or ""
        if "/cdn-cgi/l/email-protection#" in href:
            self.cf_emails.append(href.split("#", 1)[1])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "template"):
            if self._in_ld and tag == "script":
                self._in_ld = False
                self.ld_json.append("".join(self._ld_buf))
            elif self._skip:
                self._skip -= 1
            return
        if tag == "title":
            self._in_title = False
        elif tag == "a" and self._a_stack:
            href, txt = self._a_stack.pop()
            self.links.append((href, " ".join("".join(txt).split())))
        elif tag == "form" and self._form is not None:
            self.forms.append(self._form)
            self._form = None
        elif tag in ("p", "div", "li", "tr", "section"):
            self.text.append("\n")

    def handle_data(self, data):
        if self._in_ld:
            self._ld_buf.append(data)
            return
        if self._skip:
            return
        if self._in_title:
            self.title += data
        self.text.append(data)
        for a in self._a_stack:
            a[1].append(data)


def _cf_decode(hexstr):
    try:
        key = int(hexstr[:2], 16)
        return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))
    except ValueError:
        return None


EMAIL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+'-]{0,63}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}\.)+[A-Za-z]{2,24}")
OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9._%+-]{1,64})\s*[\[\(\{]\s*at\s*[\]\)\}]\s*([A-Za-z0-9-]+(?:\s*(?:[\[\(\{]\s*dot\s*[\]\)\}]|\.)\s*[A-Za-z0-9-]+)+)",
    re.I,
)
BAD_EMAIL_DOMAINS = (
    "example.com", "example.org", "domain.com", "yourdomain.com", "email.com", "sentry.io", "wixpress.com",
    "sentry-next.wixpress.com", "godaddy.com", "squarespace.com", "wix.com", "mysite.com", "yoursite.com",
    "website.com", "company.com", "test.com", "sample.com", "addresshere.com", "wordpress.com", "weebly.com",
    "latofonts.com", "typekit.net", "mailchimp.com", "yourschool.com", "school.com", "schoolname.com",
    "yourschool.ac.ke", "schoolname.sc.ke", "templatemonster.com", "themeforest.net", "elegantthemes.com",
)
BAD_EMAIL_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "ico", "bmp", "tif", "tiff", "mp4", "pdf"}
BAD_LOCAL = re.compile(r"^(?:your|name|email|user|username|someone|example|john\.?doe|jane\.?doe|first\.?last|"
                       r"firstname|you|me|xxx+|test|noreply|no-reply|donotreply|do-not-reply|mailer-daemon|"
                       r"postmaster|abuse|wordpress|privacy|dmca|themesupport|yourname|youremail)$", re.I)
FREE_MAIL = {"gmail.com", "yahoo.com", "yahoo.co.uk", "yahoo.co.ke", "hotmail.com", "outlook.com", "live.com",
             "ymail.com", "rocketmail.com", "icloud.com", "aol.com", "msn.com", "hotmail.co.uk", "googlemail.com",
             "protonmail.com", "mail.com", "zoho.com", "africaonline.co.ke", "swiftmail.co.ke"}
ROLE_WORDS = {
    "principal": "principal", "headteacher": "principal", "headmaster": "principal", "headmistress": "principal",
    "head": "principal", "deputy": "deputy", "deputyprincipal": "deputy", "admissions": "admissions",
    "admission": "admissions", "enrol": "admissions", "enroll": "admissions", "enquiries": "general",
    "enquiry": "general", "inquiries": "general", "info": "general", "contact": "general", "hello": "general",
    "office": "office", "admin": "office", "administration": "office", "secretary": "office",
    "reception": "office", "school": "general", "bursar": "accounts", "accounts": "accounts",
    "finance": "accounts", "fees": "accounts", "director": "director", "registrar": "admissions",
}

# Kenyan numbers: +254 then 9 digits. Mobiles start 7 or 1 (0722..., 0110...);
# landlines carry a 2-digit area code (020 Nairobi, 057 Kisumu, 041 Mombasa, ...).
PHONE_RE = re.compile(
    r"(?<![\d+])(?:\+?\s?254[\s.\-]?(?:\(0\)[\s.\-]?)?|0)"
    r"(?:(7\d{2}|1[0-2]\d)[\s.\-]?(\d{3})[\s.\-]?(\d{3})|([2-6]\d)[\s.\-/]?(\d{3})[\s.\-]?(\d{3,4}))(?!\d)")
FAX_NEAR = re.compile(r"fax|facsimile", re.I)
POBOX_RE = re.compile(
    r"\bP\.?\s?O\.?\s*BOX\s*(?:NO\.?\s*)?(\d{1,6})\s*(?:[-–—,/]\s*|\s+)?(\d{5})?\s*[,.\-–—]?\s*"
    r"((?:[A-Z][A-Za-z'\-]+)(?:\s[A-Z][A-Za-z'\-]+)?)?", re.I)
NOT_TOWN = {"Kenya", "Tel", "Telephone", "Phone", "Mobile", "Cell", "Email", "E", "Fax", "Website", "Location",
            "Postal", "Code", "Road", "Street", "Box", "Contact", "Us", "Call", "Physical", "Address", "Off"}
STUDENTS_RE = re.compile(r"(?:over|more than|about|approximately|nearly|of|has|with|enrol+ment of)\s+"
                         r"(\d{1,2}[,\s]?\d{3}|\d{2,3})\s*\+?\s*(?:students|pupils|learners|girls|boys)", re.I)


def normalize_phone(raw):
    """'0722 699 646' -> '+254 722 699 646'; None if it isn't a Kenyan number."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw).split(";")[0].split("/")[0])
    if digits.startswith("254"):
        digits = digits[3:]
    elif digits.startswith("0"):
        digits = digits[1:]
    if digits.startswith("0"):
        digits = digits[1:]  # "+254 (0) 722..."
    if len(digits) != 9 or digits[0] not in "1234567":
        return None
    if len(set(digits)) <= 2 or digits in ("700000000", "712345678", "123456789"):
        return None
    if digits[0] in "71":
        return f"+254 {digits[:3]} {digits[3:6]} {digits[6:]}"
    return f"+254 {digits[:2]} {digits[2:5]} {digits[5:]}"


def phone_kind(phone):
    return "mobile" if phone and phone[5] in "71" else "landline"


def normalize_url(raw):
    if not raw:
        return None
    u = str(raw).strip().split()[0].rstrip("/.,;")
    if not u or "@" in u.split("/")[0]:
        return None
    if not re.match(r"^https?://", u, re.I):
        u = "http://" + u
    host = re.sub(r"^https?://", "", u, flags=re.I).split("/")[0].lower()
    if "." not in host:
        return None
    return u


def format_pobox(box, code, town):
    town = town if town and town.split()[0] not in NOT_TOWN else None
    if town and len(town.split()) == 2 and town.split()[1] in NOT_TOWN:
        town = town.split()[0]
    out = f"P.O. Box {box}"
    if code:
        out += f"-{code}"
    if town:
        out += f", {town.title() if town.isupper() else town}"
    return out


SOCIAL_PATTERNS = [
    ("facebook", re.compile(r"^https?://(?:www\.|m\.|web\.)?facebook\.com/(?!sharer|share|dialog|plugins|tr\b|events/|login|groups/.+/permalink|photo)([A-Za-z0-9.\-_/%]+?)/?(?:\?.*)?$", re.I)),
    ("instagram", re.compile(r"^https?://(?:www\.)?instagram\.com/(?!p/|reel/|explore/|accounts/)([A-Za-z0-9._]+)/?", re.I)),
    ("youtube", re.compile(r"^https?://(?:www\.|m\.)?youtube\.com/(?:(?:channel|c|user)/[A-Za-z0-9_\-]+|@[A-Za-z0-9._\-]+)", re.I)),
    ("x", re.compile(r"^https?://(?:www\.)?(?:twitter|x)\.com/(?!intent|share|home|hashtag|search)([A-Za-z0-9_]{1,15})/?(?:\?.*)?$", re.I)),
    ("tiktok", re.compile(r"^https?://(?:www\.)?tiktok\.com/@[A-Za-z0-9._]+", re.I)),
    ("linkedin", re.compile(r"^https?://(?:www\.)?linkedin\.com/(?:company|school)/[A-Za-z0-9\-_%]+", re.I)),
]
GENERIC_SOCIAL_ACCOUNTS = {
    "facebook": {"facebook", "wix", "squarespace", "search", "sharer.php", "share.php", "photo.php", "dialog",
                 "plugins", "tr", "events", "login", "elegantthemes", "wordpress"},
    "instagram": {"wix", "squarespace", "p", "reel", "explore", "accounts"},
    "youtube": {"wix", "watch", "playlist", "shorts"},
    "x": {"wix", "intent", "share", "home", "search", "hashtag", "elegantthemes", "wordpress"},
}


def social_profile_is_specific(kind, url):
    """Reject platform/template links that cannot identify this school."""
    parsed = urlsplit(unquote(url))
    hosts = {"facebook": {"facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com"},
             "instagram": {"instagram.com", "www.instagram.com"},
             "youtube": {"youtube.com", "www.youtube.com", "m.youtube.com"},
             "x": {"x.com", "www.x.com", "twitter.com", "www.twitter.com"},
             "tiktok": {"tiktok.com", "www.tiktok.com"},
             "linkedin": {"linkedin.com", "www.linkedin.com"}}
    expected = hosts.get(kind)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or (expected and host not in expected):
        return False
    parts = [p.lower() for p in parsed.path.strip("/").split("/") if p]
    if kind == "facebook" and parts and parts[0] == "profile.php":
        return bool(re.fullmatch(r"\d{5,25}", parse_qs(parsed.query).get("id", [""])[0]))
    return bool(parts) and parts[0] not in GENERIC_SOCIAL_ACCOUNTS.get(kind, set())


def normalize_social_profile(kind, url):
    parsed = urlsplit(url)
    if kind == "facebook" and parsed.path.strip("/").lower() == "profile.php":
        profile_id = parse_qs(parsed.query)["id"][0]
        return f"https://www.facebook.com/profile.php?id={profile_id}"
    return url.split("?", 1)[0].rstrip("/")


# ---- school leaders
TITLES = (r"Chief Principal|Senior Principal|Principal|Deputy Principal|Head ?Teacher|Head ?Master|Head ?Mistress|"
          r"Deputy Head ?Teacher|Deputy Head|School Director|Managing Director|Executive Director|Director|"
          r"Founder|Proprietor|School Manager|Manager|School Administrator|Administrator|Vice[- ]Chancellor|"
          r"Chairman,? Board of Management|Chairperson,? Board of Management|Chair(?:man|person)?,? B\.?O\.?M\.?|"
          r"B\.?O\.?M\.? Chair(?:man|person)?|Bursar|Registrar|Dean of Studies|Chief Executive Officer|CEO")
_SURNAME = r"(?:Mc[A-Z][a-z]+|O'[A-Z][a-z]+|[A-Z][a-z]+-[A-Z][a-z]+|[A-Z][a-z]{1,20})"
# Name parts are joined by plain spaces only, so a name never runs on into the next line.
_NAME = r"([A-Z][a-z]{1,15}(?: [A-Z]\.)?(?: " + _SURNAME + r"){1,2})(?![a-z])"
_HON = r"(?:(?:Mr|Mrs|Ms|Miss|Dr|Prof|Rev|Fr|Sr|Br|Madam|Mdm|Eng|Hon|Pastor|Bishop)\.? +)*"
PERSON_TITLE_FIRST = re.compile(r"\b(" + TITLES + r") *[:\-–—,|]? *" + _HON + _NAME)
PERSON_NAME_FIRST = re.compile(_HON + _NAME + r"\s*[,\-–—|(]\s*(?:the\s+)?(" + TITLES + r")\b")
NAME_STOP = {
    "School", "Schools", "Academy", "College", "Primary", "Secondary", "High", "Girls", "Boys", "Mixed", "Day",
    "Boarding", "Kenya", "County", "Nairobi", "Mombasa", "Kisumu", "Nakuru", "Eldoret", "Welcome", "Contact",
    "Email", "Phone", "Staff", "Meet", "About", "Office", "Message", "Team", "The", "And", "Of", "Board",
    "Management", "Parents", "Students", "Pupils", "Learners", "Admissions", "Admission", "Fees", "Home", "Read",
    "More", "Click", "Here", "Location", "Visit", "News", "Events", "Gallery", "Our", "Mission", "Vision",
    "Motto", "Values", "Principal", "Deputy", "Head", "Teacher", "Teachers", "Director", "Manager", "Chairman",
    "Chairperson", "Junior", "Senior", "Kcse", "Kcpe", "Kpsea", "Kjsea", "Cbc", "Grade", "Form", "Term",
    "Department", "Club", "Clubs", "Sports", "Games", "Library", "Laboratory", "Science", "Mathematics",
    "English", "Kiswahili", "Christian", "Religious", "Education", "Ministry", "Catholic", "Anglican", "Church",
    "Holy", "Saint", "St", "Mary", "Joseph", "Jesus", "Christ", "God", "Lord", "Road", "Street", "Box", "Tel",
    "Mobile", "Profile", "Bio", "Information", "Page", "Video", "Calendar", "Academic", "Academics", "Registrar",
    "Bursar", "Administrator", "Founder", "Proprietor", "Dean", "Studies", "Chief", "Executive", "Officer",
    "Vice", "Chancellor", "Speech", "Note", "Remarks", "Desk", "From", "Word", "Dear", "Esteemed", "Welcome",
    "Hon", "Former", "Late", "Acting", "Interim", "Current", "New", "Outgoing", "Incoming",
}
TITLE_CANON = [
    (re.compile(r"chief principal|senior principal|^principal", re.I), "Principal", 10),
    (re.compile(r"^head ?(?:teacher|master|mistress)", re.I), "Head teacher", 10),
    (re.compile(r"vice[- ]chancellor", re.I), "Vice-Chancellor", 10),
    (re.compile(r"school director|managing director|executive director|^director|founder|proprietor|ceo|chief executive", re.I), "Director", 8),
    (re.compile(r"manager|administrator", re.I), "School manager", 6),
    (re.compile(r"deputy", re.I), "Deputy principal", 5),
    (re.compile(r"board of management|b\.?o\.?m", re.I), "BOM chair", 5),
    (re.compile(r"registrar|dean", re.I), "Registrar / dean", 4),
    (re.compile(r"bursar", re.I), "Bursar", 3),
]


def canonical_title(raw):
    for rx, label, rank in TITLE_CANON:
        if rx.search(raw):
            return label, rank
    return raw, 2


PARKED = re.compile(
    r"domain (?:is|may be) for sale|buy this domain|this domain has expired|domain has been registered|"
    r"parked (?:free|domain|by)|hugedomains|sedoparking|dan\.com|account (?:has been )?suspended|"
    r"future home of|coming soon.{0,40}godaddy|this site can.t be reached|website is under construction|"
    r"default web site page|welcome to nginx|apache2 (?:ubuntu|debian) default page|index of /",
    re.I,
)
CLOSED = re.compile(r"school (?:has|have) (?:permanently )?closed|(?:has|have) (?:officially )?closed (?:its|our) doors|"
                    r"is (?:now )?permanently closed", re.I)

CONTACT_LINK = re.compile(r"contact|get[-_ ]?in[-_ ]?touch|reach[-_ ]?us|enquir|inquir|location|find[-_ ]?us|admission", re.I)
CONTACT_PAGE_LINK = re.compile(r"contact|get[-_ ]?in[-_ ]?touch|reach[-_ ]?us|enquir|inquir", re.I)
ABOUT_LINK = re.compile(r"principal|head[-_ ]?teacher|message|staff|leadership|administration|management|"
                        r"our[-_ ]?team|about|who[-_ ]?we[-_ ]?are|history|board", re.I)


def registrable(host):
    host = (host or "").lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "or", "ac", "sc", "go", "ne", "me", "info", "mobi", "org", "com",
                                         "net", "edu") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def clean_email(raw):
    e = unquote(raw or "").strip().strip(".,;:'\"()<>[]").lower()
    e = e.split("?")[0]
    if e.startswith("mailto:"):
        e = e[7:]
    if not EMAIL_RE.fullmatch(e):
        return None
    local, domain = e.rsplit("@", 1)
    if re.match(r"^\d{8,}[a-z]", local):
        return None  # a nearby phone number was joined to the address
    tld = domain.rsplit(".", 1)[-1]
    if tld in BAD_EMAIL_TLDS or re.search(r"@\d+x\.", e) or "@2x" in e:
        return None
    if any(domain == d or domain.endswith("." + d) for d in BAD_EMAIL_DOMAINS):
        return None
    if BAD_LOCAL.match(local) or len(local) > 48 or re.fullmatch(r"[0-9a-f]{16,}", local):
        return None
    return e


def email_role(email):
    local = re.sub(r"[^a-z]", "", email.split("@")[0])
    for word, role in ROLE_WORDS.items():
        if local == word or (len(word) >= 5 and (local.startswith(word) or local.endswith(word))):
            return role
    return None


def extract(html, page_url):
    p = _Parser()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    text = htmllib.unescape("".join(p.text))
    text = re.sub(r"[ \t\r\f\v ]+", " ", text)
    out = {"emails": {}, "phones": {}, "socials": {}, "people": {}, "addresses": {}, "links": [],
           "contact_pages": [], "visible_text": text[:6000], "students": None,
           "has_contact_form": any((any(re.search(r"message|comment|textarea", field) for field in form["fields"])
                                    or (any("email" in field for field in form["fields"])
                                        and any("name" in field for field in form["fields"])))
                                   and not re.search(r"search|newsletter|login|sign[-_]?in|subscribe", form["action"], re.I)
                                   for form in p.forms),
           "title": " ".join(p.title.split())[:200], "description": p.description,
           "parked": bool(PARKED.search(p.title + " " + text[:3000])),
           "closed_hint": bool(CLOSED.search(text))}

    def add_email(raw, weight, context=None):
        e = clean_email(raw)
        if e:
            cur = out["emails"].setdefault(e, {"weight": 0, "context": context})
            cur["weight"] += weight

    def add_phone(raw, weight, label=None):
        ph = normalize_phone(raw)
        if ph:
            cur = out["phones"].setdefault(ph, {"weight": 0, "label": label})
            cur["weight"] += weight
            if label == "fax":
                cur["label"] = "fax"

    for href, txt in p.links:
        h = href.strip()
        low = h.lower()
        if low.startswith("mailto:"):
            for part in h[7:].split(","):
                add_email(part, 3, txt)
        elif low.startswith("tel:"):
            add_phone(unquote(h[4:]), 3)
        elif "wa.me/" in low or "api.whatsapp.com" in low:
            m = re.search(r"(?:wa\.me/|phone=)(\+?\d{9,13})", h)
            if m:
                add_phone(m.group(1), 2, "WhatsApp")
        elif low.startswith(("http://", "https://", "/")) or not re.match(r"^[a-z]+:", low):
            absu = urljoin(page_url, h)
            for kind, rx in SOCIAL_PATTERNS:
                if rx.match(absu) and social_profile_is_specific(kind, absu):
                    out["socials"].setdefault(kind, normalize_social_profile(kind, absu))
                    break
            else:
                out["links"].append((absu, txt))
                if CONTACT_PAGE_LINK.search(urlsplit(absu).path) and absu.startswith(("http://", "https://")):
                    out["contact_pages"].append(absu.split("#", 1)[0])

    for hexstr in p.cf_emails:
        dec = _cf_decode(hexstr)
        if dec:
            add_email(dec, 3)
    for m in EMAIL_RE.finditer(text):
        add_email(m.group(0), 1)
    for m in OBFUSCATED_RE.finditer(text):
        dom = re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*|\s*\.\s*", ".", m.group(2), flags=re.I)
        add_email(f"{m.group(1)}@{dom}", 2)
    for m in PHONE_RE.finditer(text):
        before = text[max(0, m.start() - 18):m.start()]
        add_phone(m.group(0), 1, "fax" if FAX_NEAR.search(before) else None)
    for m in POBOX_RE.finditer(text):
        addr = format_pobox(m.group(1), m.group(2), m.group(3))
        out["addresses"][addr] = out["addresses"].get(addr, 0) + (2 if m.group(2) else 1)
    counts = []
    for m in STUDENTS_RE.finditer(text):
        n = int(re.sub(r"\D", "", m.group(1)))
        if 20 <= n <= 15000:
            counts.append(n)
    out["students"] = max(counts) if counts else None

    for block in p.ld_json:
        try:
            data = json.loads(block.strip())
        except (ValueError, TypeError):
            continue
        for obj in _walk(data):
            if not isinstance(obj, dict):
                continue
            if isinstance(obj.get("telephone"), str):
                add_phone(obj["telephone"], 2)
            if isinstance(obj.get("email"), str):
                add_email(obj["email"], 2)
            same = obj.get("sameAs")
            for url in ([same] if isinstance(same, str) else same or []):
                if isinstance(url, str):
                    for kind, rx in SOCIAL_PATTERNS:
                        if rx.match(url) and social_profile_is_specific(kind, url):
                            out["socials"].setdefault(kind, normalize_social_profile(kind, url))
    _people(text, out["people"])
    return out


def _walk(obj, depth=0):
    if depth > 6:
        return
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, (dict, list)):
                yield from _walk(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, depth + 1)


def _valid_name(name):
    parts = name.split()
    return 2 <= len(parts) <= 4 and not any(p.strip(".") in NAME_STOP for p in parts)


def clean_person(name, context=""):
    """Trim words borrowed from the school's own name or town; None if nothing name-like is left."""
    ctx = {w.lower() for w in re.findall(r"[A-Za-z]+", context or "")}
    parts = name.split()
    while len(parts) > 2 and (parts[-1].lower() in ctx or parts[-1].strip(".") in NAME_STOP):
        parts.pop()
    if not _valid_name(" ".join(parts)):
        return None
    if sum(p.lower() in ctx for p in parts if len(p) > 2) >= len(parts) - 1:
        return None  # the school's own name, not a person
    return " ".join(parts)


def _people(text, people):
    def add(name, raw_title):
        name = " ".join(name.split())
        if not _valid_name(name):
            return
        title, rank = canonical_title(raw_title)
        if name not in people or people[name]["rank"] < rank:
            people[name] = {"title": title, "rank": rank}

    for m in PERSON_TITLE_FIRST.finditer(text):
        add(m.group(2), m.group(1))
    for m in PERSON_NAME_FIRST.finditer(text):
        add(m.group(1), m.group(2))
