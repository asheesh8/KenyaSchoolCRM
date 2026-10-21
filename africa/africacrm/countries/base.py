"""What the CRM needs to know about a country. Adding a country = one small module like ke.py."""

import re
from datetime import datetime, timedelta, timezone


class Country:
    code = ""                  # ISO 3166-1 alpha-2
    name = ""
    flag = ""
    slug = ""                  # file names: <slug>-schools.jsonl
    dial = ""                  # international calling code, digits only
    nsn_length = 9             # digits after the calling code
    phone_groups = (3, 3, 3)   # how a national number is spaced
    mobile_prefixes = ()       # national-number prefixes that are mobiles (WhatsApp-capable)
    utc_offset = 0             # hours; none of the current countries uses daylight saving
    timezone_name = "GMT"
    province_label = "Province"
    district_label = "District"
    area_label = "Area"
    level_labels = {}          # shared level key -> local name, e.g. lower_secondary -> "JSS"
    level_details = {}         # shared level key -> grades, e.g. "JSS 1-3"
    districts = {}             # canonical district -> province (empty = take them from the data)
    census = {}                # district -> schools counted by the national census, when published
    census_total = None
    census_note = ""
    aliases = {}               # lower-case spelling / town -> canonical district
    name_rules = ()            # extra (regex, [levels]) rules tried before the shared ones
    data_law = ""
    sources_note = ""

    # ---------- phones ----------

    def clean_phone(self, p):
        """Any local or international spelling -> '+DIAL NN NNN NNN'. Foreign numbers kept as written."""
        raw = (p or "").strip()
        digits = re.sub(r"\D", "", raw)
        if not digits:
            return None
        if digits.startswith("00"):
            digits = digits[2:]
        n = self.nsn_length
        if digits.startswith(self.dial) and len(digits) == len(self.dial) + n:
            d = digits[len(self.dial):]
        elif len(digits) == n + 1 and digits.startswith("0"):
            d = digits[1:]
        elif len(digits) == n and not raw.startswith("+"):
            d = digits
        elif raw.startswith("+") and len(digits) >= 8:
            return "+" + digits
        else:
            return None
        parts, i = [], 0
        for g in self.phone_groups:
            parts.append(d[i:i + g])
            i += g
        if i < len(d):
            parts[-1] += d[i:]
        return f"+{self.dial} " + " ".join(parts)

    def is_mobile(self, phone):
        digits = re.sub(r"\D", "", phone or "")
        if not digits.startswith(self.dial):
            return False
        nsn = digits[len(self.dial):]
        return len(nsn) == self.nsn_length and nsn.startswith(tuple(self.mobile_prefixes))

    # ---------- places ----------

    def canonical_district(self, value):
        if not value:
            return None
        v = re.sub(r"\s+", " ", str(value)).strip()
        for d in self.districts:
            if v.lower() == d.lower():
                return d
        key = re.sub(r"\b(district|county|city|municipality)\b", "", v.lower()).strip()
        for d in self.districts:
            if key == d.lower():
                return d
        hit = self.aliases.get(key) or self.aliases.get(v.lower())
        if hit:
            return hit
        # Countries without a fixed list keep whatever the data says, tidied.
        return None if self.districts else v.title() if v.isupper() or v.islower() else v

    def district_from_text(self, *texts):
        """Best guess from a town or address. Returns None rather than guess wildly."""
        if not self.districts:
            return None
        for t in texts:
            if not t:
                continue
            for d in self.districts:
                if str(t).strip().lower() == d.lower():
                    return d
            low = " " + re.sub(r"[^a-z0-9 ]", " ", str(t).lower()) + " "
            for alias, dist in sorted(self.aliases.items(), key=lambda kv: -len(kv[0])):
                if len(alias) >= 4 and f" {alias} " in low:
                    return dist
        return None

    def province(self, district):
        return self.districts.get(district)

    # ---------- time ----------

    def local_time(self, t):
        return datetime.fromtimestamp(t, timezone.utc) + timedelta(hours=self.utc_offset)

    # ---------- for the browser ----------

    def public(self):
        from .. import levels
        return {
            "code": self.code, "name": self.name, "flag": self.flag, "dial": self.dial,
            "timezone": self.timezone_name, "utc_offset": self.utc_offset,
            "province_label": self.province_label, "district_label": self.district_label,
            "area_label": self.area_label,
            "levels": [{"value": k, "label": self.level_labels.get(k, levels.LABEL[k]),
                        "detail": self.level_details.get(k, "")} for k in levels.KEYS],
            "mobile_prefixes": list(self.mobile_prefixes), "nsn_length": self.nsn_length,
            "census_total": self.census_total, "census_note": self.census_note,
            "data_law": self.data_law, "sources_note": self.sources_note,
        }
