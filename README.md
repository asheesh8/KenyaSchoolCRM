# Kenya Schools Directory

A database of every school in Kenya, from nursery (PP1) to university, with a simple CRM for contacting them.

- **Harvester** (`harvest/`): builds the directory from public sources. It then finds each school's website and reads it for emails, phone numbers, P.O. Box addresses, and the principal's or head teacher's name.
- **CRM** (`ui/`, served by `harvest/server.py`): lets you search and filter by grade, county, population, size, and more. It tracks outreach stage, notes, calls, and visits, and exports lists.

It uses plain Python 3 (standard library only) and a single SQLite file, with no build step and nothing to install.

**Live:** https://kenya-school-crm.vercel.app — `ui/` is the static front end and `api/index.py` runs the same API handler as the local server (`harvest/server.py`) as a Vercel Python function. Environment variables (names only): `APP_PASSWORD`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`; see *Configuration* below for the rest.

## Quick start

```bash
npm run dev            # or: python3 -m harvest serve   → http://127.0.0.1:8130
```

The password is read from `.env` (`APP_PASSWORD=...`). That file stays on this computer and is not committed.

To build or refresh the data:

```bash
python3 -m harvest all                  # everything free, in order (resumable)
python3 -m harvest all --skip-crawl     # just the directory, no website visits (~5 min)
```

| Step | What it does | Time |
|---|---|---|
| `areas` | 47 counties and 290 constituencies, with 2019 census and WorldPop 2020 populations | ~3 min |
| `moe` | Ministry of Education school list: 72,017 rows folded into ~47,000 schools | ~2 min |
| `osm` | OpenStreetMap schools: phones, emails, head teachers, enrolment, fees, and newer schools | ~1 min + download |
| `wikidata` | Official websites for well-known schools and universities | ~2 min |
| `dedupe` | Folds duplicate map records together | seconds |
| `discover` | Finds school websites by checking the `.sc.ke` / `.ac.ke` addresses each school's name suggests | ~1–2 h for all secondary and tertiary schools |
| `crawl` | Reads every known website for contacts | minutes per few hundred sites |
| `places` | *(optional, paid)* Google Places phone numbers and websites | see below |

Every step accepts `--counties Nairobi,Kisumu`. `discover`, `crawl` and `places` also take `--limit`, `--stale-days` and `--workers`, and `discover` and `places` take `--levels senior,tvet,university`.

## Where the data comes from

| Source | What it gives | Licence |
|---|---|---|
| Ministry of Education school list (2010 edition, via [HDX](https://data.humdata.org/dataset/kenya-schools)) | Every registered school: level, public/private, sponsor, classrooms, location | Open |
| [World Bank / MoE 2017 edition](https://energydata.info/dataset/kenya-schools) | Same, newer | CC BY 4.0 |
| OpenStreetMap (Overpass API) | Phones, emails, websites, head teachers, enrolment, fees, curriculum, schools opened since 2010 | ODbL, © OpenStreetMap contributors |
| Wikidata | Official websites | CC0 |
| OCHA / IEBC boundaries (HDX `cod-ab-ken`) | County and constituency shapes | Open |
| KNBS 2019 Census (HDX `cod-ps-ken`) | County population and ages 5–19 | Open |
| WorldPop 2020 (UN-adjusted, 1 km) | Constituency populations and population density around each school | CC BY 4.0 |
| Each school's own website | Emails, phones, P.O. Box, principal / head teacher / director / BOM chair | Read politely, robots.txt honoured |

**The 2017 World Bank file.** energydata.info puts the download behind a browser check, so the harvester doesn't fetch it. To include it, open the link above in a browser and save `schools.json` as `data/cache/wb_schools.json`. Then run `python3 -m harvest moe`, and its rows fold into the same schools.

## How schools are counted and levelled

The 2010 list records each *teaching unit* separately, so a village school usually appears once as its ECD centre and again as its primary school. The `moe` step folds rows at the same site with the same (or nearly the same) name into one school. Secondary schools, colleges and universities stay separate records, because in Kenya they are separate institutions with their own principal, even when they share a compound and a name with a primary school.

Every school is filed under the CBC structure:

| Stage | Grades |
|---|---|
| Nursery (pre-primary / ECDE) | PP1–PP2 |
| Primary | Grades 1–6 |
| Junior School | Grades 7–9 |
| Senior / Secondary | Grades 10–12 (Forms 1–4) |
| Post-secondary | TVET, teacher training, universities |

Junior School has been housed mostly in primary schools since 2023, and the 2010 list can't show that. The grade filter therefore counts primary schools for Grades 7–9 by default; untick the option to see only schools known to teach them. OpenStreetMap may add nursery or Junior School to a Ministry school. It adds secondary only when the map name says so, because many Kenyan primaries are mapped with `isced:level=2;3;4`.

## Population filters

- **County population:** 2019 census (KNBS), plus the number of children aged 5–19.
- **Constituency population:** WorldPop 2020 estimate. The census publishes sub-county totals on boundaries that don't match constituencies, so they can't be joined.
- **Town or countryside:** people per km² around each school (WorldPop). 1,500+ is a town or city, 300–1,500 the edge of town, under 300 countryside, following the UN Degree of Urbanisation.
- **School size:** enrolment where known (OpenStreetMap surveys, or a number stated on the school's website); otherwise about 40 pupils per classroom from the Ministry list, clearly marked "about".

## Website discovery and crawling

Kenyan schools register their websites under `.sc.ke` (schools) and `.ac.ke` (academic institutions). For each school without a site, `discover` builds the few addresses its name suggests (`alliancegirls.sc.ke`, `alliancehighschool.ac.ke`, …) and keeps one only if the page names the school, meaning every distinctive word of the school's name appears in its title or opening text. If one guessed site matches two different schools, it is dropped from both. With `BRAVE_API_KEY` set, the Brave Search API (free tier: 2,000 queries a month) is also tried, under the same test.

`crawl` reads each site's home page plus up to four contact, principal, or about pages. It records:

- emails, ranked so the school's own domain comes first, then Gmail/Yahoo (common for Kenyan schools), with third-party addresses last;
- Kenyan phone numbers, normalised to `+254 …`, plus WhatsApp links;
- P.O. Box addresses;
- named leaders: Principal, Head teacher, Director, Deputy, BOM chair;
- enrolment stated on the site.

Every value keeps its source page and first-seen / last-seen dates. A value missing on a later visit is marked *no longer listed* rather than deleted.

The crawler honours `robots.txt`, makes at most two requests to one site at a time, and names itself in its user agent (set `HARVEST_CONTACT` to a URL or email where a school can reach you). It fetches public internet addresses only, and treats sites that answer 401/403/429 as blocked and leaves them alone.

## Google Places (optional, paid)

```bash
export GOOGLE_PLACES_API_KEY=...
python3 -m harvest places --limit 200 --levels senior
```

Each lookup is one Text Search request, billed at Google's Enterprise rate (about $35 per 1,000 as of 2025, with a monthly free allowance). Check current pricing first.

## Using the CRM

- **Home:** totals, schools by grade level, a county map (schools per 10,000 children, contact coverage, engagement), public/private and town/countryside splits, contact coverage, outreach stages, and recent activity.
- **Find schools:** five plain questions (which grades, which county, public or private, how big, and how you can reach them), with **More filters** for constituency, several counties, area population, faith sponsor, boys/girls, boarding, special needs, stage and tags. Phones, emails, and the head teacher show right in the list. Filters live in the URL, so a view can be bookmarked.
- **School panel:** big Call / WhatsApp / Email / Website buttons, the outreach stage, contacts with sources, a note / call / visit log, corrections to levels, tags, a small map, and nearby schools.
- **Map:** every matching school as a dot. Click one to open it.
- **Progress:** a board of stages; drag a school to move it.
- **Counties:** population, children, schools per 10,000 children, and coverage. Click through to constituencies.
- **Download list (Excel):** the current filtered list as CSV, with all emails and phones.

It uses light mode by default, with a **Dark screen** switch at the bottom left. Keyboard: `/` search · `j`/`k` move · `Enter` open · `Esc` close · `x` select · `s` star · `1`–`9` set stage.

## Before contacting schools

A listed email or phone is a lead, not a confirmed inbox; check the "seen" date. Kenya's **Data Protection Act 2019** covers personal details such as a head teacher's name and mobile number. Contact schools about school matters, say who you are, and honour requests to stop by setting the school to **Do not contact**.

## Deploying on Vercel

Same setup as the Village Servers directory: the data lives in [Turso](https://turso.tech) and a password protects the CRM.

```bash
python3 -m harvest publish                           # writes data/publish.db
turso db create kenya-schools --from-file data/publish.db
turso db show kenya-schools --url                    # → TURSO_DATABASE_URL
turso db tokens create kenya-schools                 # → TURSO_AUTH_TOKEN
```

Set `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` and `APP_PASSWORD` in the Vercel project settings, then deploy. `vercel.json` serves `ui/` as the site and `api/index.py` as the API.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `APP_PASSWORD` | from `.env` | CRM password |
| `HARVEST_DB` | `data/harvest.db` | database file |
| `HARVEST_CONTACT` | — | contact added to the crawler's user agent |
| `BRAVE_API_KEY` | — | adds web search to `discover` |
| `GOOGLE_PLACES_API_KEY` | — | enables `places` |
| `HARVEST_OVERPASS` | three public servers | Overpass endpoints |
| `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` | — | hosted database |

## Layout

```
harvest/
  __main__.py  CLI            config.py   settings, sources
  areas.py     counties, constituencies, populations, point lookup
  levels.py    CBC levels and grades, names, faith, gender, sponsor rules
  moe.py       Ministry list import and folding     osm.py      OpenStreetMap import and matching
  wikidata.py  websites from Wikidata               dedupe.py   duplicate folding
  discover.py  finds school websites                crawl.py    reads them
  extract.py   emails / +254 phones / P.O. Box / principals from HTML
  places.py    optional Google Places               net.py      polite, public-only HTTP
  db.py        SQLite schema                        server.py   CRM API + login
  remote.py    Turso client                         geo.py      point-in-polygon
api/index.py   Vercel entry point
ui/            CRM front end (HTML/CSS/JS, no build)
tests/         python3 -m unittest discover tests
.claude/skills frontend-design, web-scraping, kpi-dashboard-design (from skills.sh)
```
