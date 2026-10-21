# Africa School CRM: shared country data format (v1)

Every country ships one file, `/mnt/project-files/<country>-schools/<country>-schools.jsonl`
(e.g. `uganda-schools/uganda-schools.jsonl`), one institution per line. The CRM loads it with
`python3 -m africacrm load --country UG --file <path>` (in `africa/`). Contact data stays out of the public repo.

It is the Sierra Leone record format with three additions (`country`, `province`, `area`) and a
shared level vocabulary. Unknown fields are ignored; missing fields are null.

```json
{
  "id": "stable id, unique within the country (e.g. EMIS/UNEB/MoE code, or a hash of name+district)",
  "country": "UG",                       // ISO 3166-1 alpha-2: KE, SL, UG, ...
  "name": "official name as published",
  "kind": "school | office | secretariat | association | ngo",
  "levels": ["pre_primary","primary","lower_secondary","upper_secondary","tvet","tertiary","admin"],
  "province": "top-level grouping: UG region (Central/Eastern/Northern/Western), SL province, KE former province or null",
  "district": "UG district, SL district, KE county",
  "area":     "UG county/sub-county, SL chiefdom, KE constituency (or null)",
  "town": null, "address": null,
  "ownership": "government | government_assisted | private | community | mission | ngo | unknown",
  "denomination": "Catholic | Anglican | Islamic | SDA | ... or null",
  "website": null,
  "emails":   [{"email": "...", "source_url": "...", "confidence": "high|medium|low", "seen": null}],
  "phones":   [{"phone": "+256 7XX XXX XXX", "source_url": "..."}],
  "officials":[{"name": "...", "role": "Head Teacher|Principal|...", "email": null, "phone": null, "source_url": "..."}],
  "emis_code": null, "lat": null, "lon": null,
  "students": null,                      // enrolment if published
  "sources": ["every URL used"],
  "notes": null
}
```

## Levels (shared across countries, each country shows its own labels)

| key | Kenya | Sierra Leone | Uganda |
|---|---|---|---|
| pre_primary | PP1-PP2 | Nursery | Nursery (baby/middle/top) |
| primary | Grade 1-6 | Class 1-6 | P1-P7 |
| lower_secondary | Junior School, Grade 7-9 | JSS 1-3 | O-level, S1-S4 |
| upper_secondary | Senior School, Grade 10-12 | SSS 1-3 | A-level, S5-S6 |
| tvet | TVET | Technical/vocational | BTVET / technical institutes |
| tertiary | University/college | University/college | University/college/PTC/NTC |
| admin | Education offices | Education offices | District education offices, foundation bodies |

The old Sierra Leone keys `junior_secondary` / `senior_secondary` are still accepted.

## Rules (same as Sierra Leone)

- Phones in international form (`+256 ...`, `+232 ...`, `+254 ...`).
- Email confidence: high = institution's own site or an official page dated 2020+; medium = directory,
  news, or older/undated official page; low = older than 2015 or ambiguous.
- Every email, phone and official must appear verbatim on its source_url. Never guess or pattern-fill an address.
