from .base import Country

_PROVINCES = {
    "Coast": ["Mombasa", "Kwale", "Kilifi", "Tana River", "Lamu", "Taita Taveta"],
    "North Eastern": ["Garissa", "Wajir", "Mandera"],
    "Eastern": ["Marsabit", "Isiolo", "Meru", "Tharaka Nithi", "Embu", "Kitui", "Machakos", "Makueni"],
    "Central": ["Nyandarua", "Nyeri", "Kirinyaga", "Murang'a", "Kiambu"],
    "Rift Valley": ["Turkana", "West Pokot", "Samburu", "Trans Nzoia", "Uasin Gishu", "Elgeyo Marakwet", "Nandi",
                    "Baringo", "Laikipia", "Nakuru", "Narok", "Kajiado", "Kericho", "Bomet"],
    "Western": ["Kakamega", "Vihiga", "Bungoma", "Busia"],
    "Nyanza": ["Siaya", "Kisumu", "Homa Bay", "Migori", "Kisii", "Nyamira"],
    "Nairobi": ["Nairobi"],
}


class Kenya(Country):
    code, name, flag, slug = "KE", "Kenya", "🇰🇪", "kenya"
    dial, nsn_length, phone_groups = "254", 9, (3, 3, 3)
    mobile_prefixes = ("7", "10", "11")
    utc_offset, timezone_name = 3, "Nairobi time (EAT)"
    province_label, district_label, area_label = "Former province", "County", "Constituency"
    level_labels = {"pre_primary": "Pre-primary", "primary": "Primary", "lower_secondary": "Junior School",
                    "upper_secondary": "Senior School", "tvet": "TVET / polytechnic",
                    "tertiary": "University / college", "admin": "Education offices"}
    level_details = {"pre_primary": "PP1-PP2", "primary": "Grade 1-6", "lower_secondary": "Grade 7-9",
                     "upper_secondary": "Grade 10-12 (Forms 1-4)", "tertiary": "incl. teacher training colleges"}
    districts = {c: p for p, cs in _PROVINCES.items() for c in cs}
    aliases = {"elgeyo-marakwet": "Elgeyo Marakwet", "tharaka-nithi": "Tharaka Nithi", "taita-taveta": "Taita Taveta",
               "muranga": "Murang'a", "murang a": "Murang'a", "nairobi city": "Nairobi", "homabay": "Homa Bay",
               "homa-bay": "Homa Bay", "trans-nzoia": "Trans Nzoia", "west-pokot": "West Pokot",
               "tana-river": "Tana River", "uasin-gishu": "Uasin Gishu", "keiyo marakwet": "Elgeyo Marakwet",
               "eldoret": "Uasin Gishu", "thika": "Kiambu", "kitale": "Trans Nzoia", "malindi": "Kilifi"}
    name_rules = ((r"\bhigh\b|\bsecondary\b|\bsec\.? sch|\bboys'?\b.*\bschool\b|\bgirls'?\b.*\bschool\b",
                   ["upper_secondary"]),)
    data_law = "Kenya's Data Protection Act 2019"
    sources_note = ("Ministry of Education school lists (2010 via HDX, 2017 via the World Bank), OpenStreetMap, "
                    "Wikidata and each school's own website, gathered by the Kenya harvester "
                    "(python3 -m harvest in the repository root).")


COUNTRY = Kenya()
