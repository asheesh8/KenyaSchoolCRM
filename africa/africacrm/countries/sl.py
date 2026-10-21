from .base import Country


class SierraLeone(Country):
    code, name, flag, slug = "SL", "Sierra Leone", "🇸🇱", "sierra-leone"
    dial, nsn_length, phone_groups = "232", 8, (2, 3, 3)
    # Landlines start 22; every other range is a mobile network.
    mobile_prefixes = ("25", "30", "31", "32", "33", "34", "7", "80", "81", "82", "83", "84", "85", "86", "87",
                       "88", "99")
    utc_offset, timezone_name = 0, "Freetown time (GMT)"
    province_label, district_label, area_label = "Province", "District", "Chiefdom"
    level_labels = {"pre_primary": "Nursery", "primary": "Primary", "lower_secondary": "JSS",
                    "upper_secondary": "SSS", "tvet": "Technical / vocational", "tertiary": "University / college",
                    "admin": "Education offices"}
    level_details = {"pre_primary": "pre-primary", "primary": "Class 1-6", "lower_secondary": "JSS 1-3",
                     "upper_secondary": "SSS 1-3"}
    # District -> province, and the 2024/25 Annual School Census school count (MBSSE 2025 ASC report, table 1-1).
    _d = {
        "Western Area Urban": ("Western Area", 1958), "Western Area Rural": ("Western Area", 1780),
        "Bombali": ("North", 885), "Falaba": ("North", 391), "Koinadugu": ("North", 317),
        "Tonkolili": ("North", 923), "Kambia": ("North West", 655), "Karene": ("North West", 450),
        "Port Loko": ("North West", 969), "Bo": ("South", 1132), "Bonthe": ("South", 331),
        "Moyamba": ("South", 601), "Pujehun": ("South", 392), "Kailahun": ("East", 591),
        "Kenema": ("East", 1137), "Kono": ("East", 932),
    }
    districts = {k: v[0] for k, v in _d.items()}
    census = {k: v[1] for k, v in _d.items()}
    census_total = 13444
    census_note = "2024/25 Annual School Census, pre-primary to senior secondary"
    aliases = {
        "western urban": "Western Area Urban", "freetown": "Western Area Urban", "western area": "Western Area Urban",
        "wau": "Western Area Urban", "western rural": "Western Area Rural", "war": "Western Area Rural",
        "waterloo": "Western Area Rural", "hastings": "Western Area Rural", "tombo": "Western Area Rural",
        "kent": "Western Area Rural", "york": "Western Area Rural", "regent": "Western Area Rural",
        "lakka": "Western Area Rural", "goderich": "Western Area Urban", "lumley": "Western Area Urban",
        "kissy": "Western Area Urban", "wellington": "Western Area Urban", "aberdeen": "Western Area Urban",
        "wilberforce": "Western Area Urban", "murray town": "Western Area Urban", "brookfields": "Western Area Urban",
        "congo cross": "Western Area Urban", "makeni": "Bombali", "kabala": "Koinadugu", "mongo": "Falaba",
        "bendugu": "Falaba", "magburaka": "Tonkolili", "mile 91": "Tonkolili", "yele": "Tonkolili",
        "bumbuna": "Tonkolili", "rokupr": "Kambia", "kamakwie": "Karene", "kamakwei": "Karene",
        "batkanu": "Karene", "portloko": "Port Loko", "lunsar": "Port Loko", "lungi": "Port Loko",
        "masiaka": "Port Loko", "bo city": "Bo", "njala": "Moyamba", "mattru jong": "Bonthe", "mano": "Moyamba",
        "zimmi": "Pujehun", "blama": "Kenema", "tongo": "Kenema", "segbwema": "Kailahun", "pendembu": "Kailahun",
        "daru": "Kailahun", "koidu": "Kono", "koidu town": "Kono", "tankoro": "Kono", "yengema": "Kono",
        "bunumbu": "Kailahun",
    }
    data_law = "Sierra Leone's Data Protection Act 2023"
    sources_note = ("MBSSE school lists and district offices, the Tertiary Education Commission, church and mission "
                    "education secretariats, school websites and OpenStreetMap, gathered by the Sierra Leone tools "
                    "(python3 -m slcrm in sierra-leone/).")


COUNTRY = SierraLeone()
