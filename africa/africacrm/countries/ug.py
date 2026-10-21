from .base import Country


class Uganda(Country):
    code, name, flag, slug = "UG", "Uganda", "🇺🇬", "uganda"
    dial, nsn_length, phone_groups = "256", 9, (3, 3, 3)
    mobile_prefixes = ("7",)
    utc_offset, timezone_name = 3, "Kampala time (EAT)"
    province_label, district_label, area_label = "Region", "District", "Sub-county"
    level_labels = {"pre_primary": "Nursery", "primary": "Primary", "lower_secondary": "O-level",
                    "upper_secondary": "A-level", "tvet": "BTVET / technical", "tertiary": "University / college",
                    "admin": "Education offices"}
    level_details = {"pre_primary": "baby, middle and top class", "primary": "P1-P7", "lower_secondary": "S1-S4",
                     "upper_secondary": "S5-S6", "tertiary": "incl. primary and national teachers' colleges"}
    # 146 districts and cities change often, so the list comes from the data; regions are fixed.
    districts = {}
    regions = ["Central", "Eastern", "Northern", "Western"]
    # In Uganda "College" or "S.S." in a name is usually a secondary school (St Mary's College Kisubi).
    name_rules = (
        (r"^(?!.*(universit|teacher|technical|polytechnic|health|nursing|medical|business|commerce|vocational))"
         r".*\bcollege\b", ["lower_secondary", "upper_secondary"]),
        (r"\bseed (secondary )?school\b|\bs\.\s?s\.?(\s|$)|\bsss\b", ["lower_secondary", "upper_secondary"]),
    )
    data_law = "Uganda's Data Protection and Privacy Act 2019"
    sources_note = "Ministry of Education and Sports lists, UNEB centre lists, school websites and directories."


COUNTRY = Uganda()
