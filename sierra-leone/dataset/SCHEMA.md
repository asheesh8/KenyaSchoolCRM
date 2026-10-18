# Raw research record schema (one JSON object per line, file raw/<worker>.jsonl)

{
 "name": "official name as published",
 "kind": "school" | "office" | "secretariat" | "association" | "ngo",
 "levels": ["pre_primary","primary","junior_secondary","senior_secondary","tvet","tertiary","admin"],
 "district": one of the 16 canonical names below, or null,
 "chiefdom": null, "town": null, "address": null,
 "ownership": "government" | "government_assisted" | "private" | "community" | "mission" | "ngo" | "unknown",
 "denomination": null or e.g. "Catholic","Methodist","Anglican","UMC","Wesleyan","Baptist","SDA","Pentecostal","Islamic","Ahmadiyya",
 "website": null,
 "emails":   [{"email": "...", "source_url": "...", "confidence": "high|medium|low", "seen": "year or date the page shows, else null"}],
 "phones":   [{"phone": "+232 ...", "source_url": "..."}],
 "officials":[{"name": "...", "role": "Principal|Head Teacher|Proprietor|Registrar|Vice Chancellor|Deputy Director of Education|Education Secretary|...", "email": null, "phone": null, "source_url": "..."}],
 "emis_code": null, "lat": null, "lon": null,
 "sources": ["every URL used"],
 "notes": null,
 "worker": "<worker slug>"
}

Canonical districts: Bo, Bombali, Bonthe, Falaba, Kailahun, Kambia, Karene, Kenema, Koinadugu, Kono, Moyamba, Port Loko, Pujehun, Tonkolili, Western Area Rural, Western Area Urban.

Confidence: high = shown on the institution's own site or an official government/church page dated 2020 or later;
medium = third-party directory, news article, or official page dated 2015-2019 or undated;
low = older than 2015, or the page is ambiguous about whose address it is.
Never guess, construct or pattern-fill an email address. Every email and phone must appear verbatim on its source_url.
