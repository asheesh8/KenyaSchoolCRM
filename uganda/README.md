# Uganda schools directory

Builds Uganda's school list with contacts in the shared Africa CRM format (country `UG`), so the
multi-country CRM can load it next to Kenya and Sierra Leone. Python 3 standard library only.

## What goes in

1. **Base list: OpenStreetMap** (HOT's Uganda export of education facilities). About 28,000 named
   schools, kindergartens, colleges and universities, each already placed in its region, district,
   county and sub-county, with coordinates. No contacts.
2. **Contacts: research files**, one JSONL per research pass in the raw folder, following
   [dataset/SCHEMA.md](dataset/SCHEMA.md): government education offices (district education officers,
   inspectors), universities and colleges, BTVET institutes, secondary schools, church and Muslim
   foundation bodies, and school directories. Every email, phone and named official carries the public
   page it was copied from.

`merge` matches the researched records onto the map's entries by name within a district (and
sub-county when both sides have one), keeps same-named schools in different sub-counties apart, and
drops any email that has no source page.

## Commands

```sh
python3 -m ugschools osm                 # download the HOT export -> raw/osm.jsonl
python3 -m ugschools osm --file x.zip    # or use a copy you already downloaded
python3 -m ugschools merge               # raw/*.jsonl -> uganda-schools.jsonl + CSVs + summary.json
python3 -m unittest discover tests
```

Folders (environment variables): `UG_RAW` for the raw files, `UG_DATASET_DIR` for the output. Both
default to the project folder (`/mnt/project-files/uganda-schools/`), because the merged contacts name
real people and are kept out of this public repository.

## Output

- `uganda-schools.jsonl`: one institution per line, the format the Africa CRM loads
  (`python3 -m africacrm load --country UG --file uganda-schools.jsonl`). `province` is the region
  (Central, Eastern, Northern, Western), `district` one of the 136 districts, `area` the sub-county.
- `schools.csv`: one row per institution, with best email, all phones, a WhatsApp-able mobile (+256 7xx)
  and the head teacher or official.
- `contacts.csv`: one row per email, phone (`whatsapp` when it is a mobile) or named official, with its
  source page.
- `summary.json`: counts by level, region, district, ownership and email confidence.

## Levels

| key | Uganda |
|---|---|
| pre_primary | Nursery (baby, middle, top class) |
| primary | P1-P7 |
| lower_secondary | O-level, S1-S4 |
| upper_secondary | A-level, S5-S6 |
| tvet | BTVET: technical institutes, UTCs, vocational centres |
| tertiary | Universities, colleges, PTCs/NTCs, nursing and health institutes |
| admin | District education offices, foundation bodies, diocesan education secretariats |

A map entry whose name gives no level is filed as primary (most Ugandan schools are), and its notes say
the level was guessed.
