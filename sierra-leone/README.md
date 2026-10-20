# Sierra Leone Schools Directory

A directory of Sierra Leone's schools, colleges and education offices, with a small CRM and a three-email outreach sequence you send from up to seven of your own mailboxes. It is the Sierra Leone counterpart of the Kenya directory in the parent folder, built the same way: plain Python 3 (standard library only), one SQLite file, and a static front end with no build step.

## Quick start

```bash
cd sierra-leone
python3 -m slcrm load        # loads dataset/sierra-leone-schools.jsonl into data/crm.db
npm run dev                  # or: python3 -m slcrm serve   → http://127.0.0.1:8140
```

Put `APP_PASSWORD=...` and `SECRET_KEY=...` in `sierra-leone/.env` (not committed). `SECRET_KEY` signs unsubscribe links and encrypts the mailbox passwords you save, so keep it the same once you've connected accounts.

## What's in the data

The merged research is **not committed** to this public repository, because it names head teachers and officials. It lives in the project's shared folder (`/mnt/project-files/sierra-leone-schools/`). Copy those files into `sierra-leone/dataset/` (git ignores them), or set `SLCRM_DATASET` to the `.jsonl` path, then run `python3 -m slcrm load`:

| File | What it is |
|---|---|
| `sierra-leone-schools.jsonl` | one institution per line: name, levels, district, chiefdom, town, ownership, faith, EMIS code, emails / phones / officials, each with the public page it came from |
| `schools.csv` | the same, one row per institution, for Excel |
| `contacts.csv` | one row per email, phone or named official, with its source URL and confidence |
| `summary.json` | counts by level, district, ownership and email confidence |

Schools are filed under Sierra Leone's structure: **Nursery** (pre-primary), **Primary** (Class 1–6), **JSS** (JSS 1–3), **SSS** (SSS 1–3), **Technical / vocational**, **University / college**, plus **Education offices** (Ministry, councils, church education secretariats, networks). A school can hold several levels.

**Rules the research followed.** Only contact details an institution or official body published. Every email, phone and named official carries the exact URL it was copied from. Nothing is guessed or pattern-filled: an address that didn't appear on a public page isn't in the data. Emails are marked:

- **high** (shown as "Confirmed source"): on the institution's own site or an official page from 2020 or later;
- **medium** ("Likely"): a directory, news story or older official page;
- **low** ("Check first"): old or ambiguous, or a free-mail address listed for more than one institution.

**What to expect.** Most Sierra Leonean primary and secondary schools publish no email at all. The bulk of the directory is the Ministry's own school lists (names, EMIS codes, chiefdoms, towns), and the reachable contacts are concentrated in universities and colleges, TVET institutes, church education secretariats, NGOs, Freetown's private and international schools, and the Ministry itself. For the thousands of schools without an email, the fastest route is usually their education secretariat (Catholic, Methodist, UMC, Anglican, Wesleyan, Islamic boards) or the district education office, both of which are in the directory.

### Refreshing and growing it

The research ran from a sandbox that could only read web pages one at a time. On your own computer these commands read the sources directly:

```bash
python3 -m slcrm mbsse    # the Ministry's published school lists (fee-subsidy schedules): EMIS, chiefdom, town, headcount
python3 -m slcrm schoollist  # the Ministry's 2016/2017 EMIS school-list PDFs: a phone number for nearly every school
python3 -m slcrm osm      # OpenStreetMap schools with coordinates and any phone / email / website on the map
python3 -m slcrm crawl    # reads every known school website for emails, +232 phones and named heads (robots.txt honoured)
python3 -m slcrm stats    # coverage by level and district, against the 2024/25 school census
```

`python3 -m slcrm merge --raw <folder>` rebuilds `dataset/` from research files in the format of `dataset/SCHEMA.md` (the project's research lives in `/mnt/project-files/sierra-leone-schools/raw/`).

`schoollist` needs `pdftotext` (`brew install poppler` on a Mac, `apt install poppler-utils` on Linux) or `pip install pypdf`. It adds the phones straight into your CRM and writes `data/schoollist.jsonl`; share that file back to the project folder so it can be merged into the shared dataset. The phones date from 2016/17, so expect some to be out of date.

Worth requesting by email (all mentioned in the research notes): MBSSE's master school list at `schoollist.mbsse.gov.sl` (13,788 schools with EMIS codes and GPS, partner access), and each district's Deputy Director of Education for their head-teacher contact lists.

## Using the CRM

- **Home:** totals, schools by level, a district table against the census, email quality, outreach stages, recent activity.
- **Find schools:** filter by level, province, district, how you can reach them, email quality, ownership, faith, stage and sequence status. Tick schools and press **Email selected**, or **Email all N with an address** for the whole filtered list. **Download list (Excel)** exports what you see.
- **School panel:** every contact with its source link and confidence, the stage, a note / call / visit log, and the school's place in the email sequence (pause, resume, "they replied", unsubscribe).
- **Email outreach:** sender accounts, the on/off switch, the three emails, who's next, what was sent, and the do-not-email list.
- **Progress:** schools by stage.

## Email outreach

### Connecting your seven mailboxes

On **Email outreach**, press **Connect a sender email**, pick the provider and paste the mailbox's **app password** (not its normal password):

| Provider | Where to get the app password | Servers (filled in for you) |
|---|---|---|
| Gmail / Google Workspace | Turn on 2-Step Verification, then myaccount.google.com/apppasswords | smtp.gmail.com:587, imap.gmail.com |
| Outlook / Microsoft 365 | Security settings → app password (SMTP AUTH must be on for the mailbox) | smtp.office365.com:587, outlook.office365.com |
| Zoho, Yahoo | Account security → app-specific password | filled in |
| Anything else | your host's SMTP settings | enter them |

Press **Test sign-in** to check it (nothing is sent). Passwords are stored encrypted with `SECRET_KEY` and never sent back to the browser. If you'd rather keep them out of the database, leave the field blank and set `SENDER_1_PASSWORD` … `SENDER_7_PASSWORD` in `.env` or the hosting settings (the number is the account's slot).

### The sequence

1. **Introduction**: who you are and the initiative; asks if they're the right contact.
2. **Library offer** (4 days later, as a reply in the same thread): the free library and your link.
3. **Follow-up** (7 days later): one last, polite try.

Edit the text, subjects and delays on the Outreach page. Set your organisation name and library link there too. Placeholders: `{{greeting}}` (e.g. "Dear Mrs Kamara," or "Dear Principal,"), `{{school}}`, `{{person}}`, `{{role}}`, `{{district}}`, `{{town}}`, `{{sender_name}}`, `{{org}}`, `{{library_link}}`, `{{signature}}`.

Pick schools, press **Email selected**, choose one account or spread them across all of them, and choose the school's main address or every address on file. Then press **Start sending**.

### Staying out of spam

Each account sends one message at a time, only while sending is switched on, and only inside its own limits:

- **Warm-up:** a new mailbox starts at 10 emails a day and adds 5 a day up to its daily cap (default 40).
- **Hourly cap** (default 10) and a **minimum gap** (default 2 minutes, plus random jitter).
- **Sending hours** 08:00–18:00 Freetown time (GMT), weekdays only by default.
- **Plain-text** emails with a real `Message-ID`, `List-Unsubscribe` headers and follow-ups threaded as replies.
- **Automatic pause:** a sign-in failure pauses the account at once; three send failures in a row pause it too. A rejected address is marked bounced.

Seven accounts at the defaults reach about 280 emails a day once warmed up. Google Workspace and paid Microsoft 365 mailboxes can safely go higher after a few weeks of good history. Free Gmail accounts sending cold email at volume do get suspended, so raise limits slowly.

### Unsubscribes, replies and bounces

- Every email ends with an unsubscribe line. Set `PUBLIC_URL` (the CRM's address) to add a one-click link; without it, people reply "unsubscribe".
- With the IMAP server filled in, the CRM reads each inbox every 15 minutes while sending (or when you press **Check replies**), without marking anything read. A reply stops that person's sequence and moves the school to **Replied**; a reply asking to stop, or a bounce, adds the address to the do-not-email list.
- Unsubscribed and bounced addresses are never emailed again, and schools set to **Do not contact** or **Not interested** are skipped.

### Sending without the browser

```bash
python3 -m slcrm send         # sends due emails inside every limit until Ctrl+C
python3 -m slcrm send --once  # one round
python3 -m slcrm replies      # check every inbox now
```

The local server (`serve`) also sends in the background while the switch is on. On Vercel there's no background process, so keep the Outreach page open while sending.

## WhatsApp and text messages

Most schools have a phone number but no email. In a school's panel, every mobile number has **WhatsApp** and **Text** buttons that open the message ready to send (WhatsApp Web or the app on a computer, the SMS app on a phone). Set your name and edit both messages under **Email outreach → WhatsApp and text messages**. Placeholders: `{{hello}}` ("Good day Mrs Kamara," or "Good day,"), `{{school}}`, `{{person}}`, `{{district}}`, `{{town}}`, `{{sender_name}}`, `{{org}}`, `{{library_link}}`. Nothing is sent automatically. Change the school's stage after you send, and mark anyone who replies STOP as **Do not contact**.

## Before contacting schools

Sierra Leone's **Data Protection Act 2023** covers personal details such as a head teacher's name and email. Email schools about school matters, say who you are, keep volumes modest, and honour every request to stop. A listed email is a lead, not a confirmed inbox: check the source link for anything marked "Check first".

## Deploying on Vercel

Create a separate Vercel project with **Root Directory** set to `sierra-leone`. Data lives in [Turso](https://turso.tech):

```bash
python3 -m slcrm publish                                  # writes data/publish.db
turso db create sierra-leone-schools --from-file data/publish.db
```

Set `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `APP_PASSWORD`, `SECRET_KEY` and `PUBLIC_URL` in the project settings, plus `SENDER_n_PASSWORD` if you keep passwords out of the database.

## Configuration

| Variable | Purpose |
|---|---|
| `APP_PASSWORD` | CRM password |
| `SECRET_KEY` | signs sessions and unsubscribe links; encrypts saved mailbox passwords |
| `PUBLIC_URL` | the CRM's public address, for one-click unsubscribe links |
| `SENDER_1_PASSWORD` … `SENDER_7_PASSWORD` | optional mailbox passwords instead of saving them in the database |
| `SLCRM_DB` | database file (default `data/crm.db`) |
| `HARVEST_CONTACT` | a URL or email added to the crawler's user agent |
| `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` | hosted database |

## Layout

```
slcrm/
  __main__.py  CLI                   config.py   settings
  levels.py    levels, districts, census counts, name / phone / email rules
  importer.py  research files → dataset/ → database (dedupe)
  mbsse.py     Ministry school lists         osm.py     OpenStreetMap
  crawl.py     school websites               net.py     polite, public-only HTTP
  mailer.py    accounts, sequence, limits, unsubscribes, reply and bounce checks
  db.py        SQLite schema                 server.py  CRM API + login + unsubscribe page
  remote.py    Turso client
api/index.py   Vercel entry point
ui/            CRM front end (HTML/CSS/JS, no build)
dataset/       the merged research
tests/         python3 -m unittest discover tests
```
