# Africa Schools CRM

One CRM for schools in **Kenya, Sierra Leone and Uganda**, with room for more countries. You pick a country at the top (or "All"), find schools, email them in sequences spread across up to 7 of your own mailboxes, work through a WhatsApp queue, and see every reply in one place.

It is plain Python 3 (standard library only) with a static UI: no build step and nothing to install. Data lives in one SQLite file locally, or in Turso when deployed.

This replaces the separate Kenya (`harvest/`, `ui/`) and Sierra Leone (`sierra-leone/`) CRMs for outreach. The Kenya harvester still builds the Kenya directory, and the live Kenya site is untouched.

## Quick start

```bash
cd africa
python3 -m africacrm load                          # Sierra Leone + Uganda from the project folder
python3 -m africacrm import-kenya --db ../data/harvest.db   # Kenya, with its stages, notes and history
python3 -m africacrm serve                         # → http://127.0.0.1:8150
```

`load` looks in `dataset/` first, then `/mnt/project-files/<country>-schools/` (set `AFRICACRM_PROJECT_FILES` to change that). Use `--country UG` or `--file path.jsonl` for one file. Running it again refreshes the directory and keeps everything you did in the CRM (stages, notes, sequences, WhatsApp outcomes).

For Kenya you can pull from the live Kenya CRM instead: `import-kenya --turso-url libsql://… --turso-token …`. It only reads that database.

The file format every country uses is in [`dataset/DATA-FORMAT.md`](dataset/DATA-FORMAT.md). A new country needs one file in that format plus a small `africacrm/countries/<cc>.py` (dial code, mobile prefixes, time zone, district labels).

## The flow

1. **Email → Connect accounts.** Add up to 7 mailboxes. For Gmail or Google Workspace, turn on 2-step verification and create an *app password* (myaccount.google.com → Security → App passwords); use `smtp.gmail.com:587` and `imap.gmail.com:993`. Outlook/Microsoft 365 uses `smtp.office365.com:587`. You can limit an account to certain countries.
2. **Email → Your details and templates.** Your name, organisation and link fill the templates. There is one shared 3-step sequence, and any country can override any step.
3. **Pick who to email.** On the Email page choose country, level and district, or on Schools filter and press *Email all N*. Give the batch a campaign name. Schools are shared out to the least-busy allowed account.
4. **Sending.** Each account sends on weekdays inside the school's *local* working hours (Kenya and Uganda UTC+3, Sierra Leone UTC+0), with a warm-up (starts small, grows daily), daily and hourly caps, and a random gap between emails. An account pauses itself after repeated failures. Every email carries an unsubscribe link and header.
5. **Replies.** Inboxes are checked over IMAP. A reply stops that school's sequence and appears on **Replies** with a snippet; "stop / unsubscribe" replies and bounces go on the do-not-email list automatically. Mark each reply Interested, Partner or Not interested.

Locally, `serve` sends in the background. `python3 -m africacrm send` and `replies` do the same from a terminal or a scheduler.

## WhatsApp

**Queue (built in, free).** The WhatsApp page shows one school at a time that has a mobile number and hasn't been messaged. *Open WhatsApp* opens a chat with your message already typed (a `wa.me` link, which works on WhatsApp Web, Desktop or your phone). You press send in WhatsApp, then record what happened: sent, sent by SMS instead, replied, not on WhatsApp, wrong number, or skip. The school's stage updates and the queue moves on. There's a daily target, and a message per country.

Keep it safe for your number: send a few dozen a day, personalise the opening, stop if people report you, and use a WhatsApp Business app number rather than a personal one.

**WhatsApp Business Platform (optional, later).** For sending at volume from the CRM itself you'd need Meta's Cloud API: a Meta Business account, a verified business, a dedicated number, and *pre-approved message templates* for first contact (businesses can't send free-form first messages). Meta charges per conversation, varying by country. It also needs a webhook for replies. It's worth it once the manual queue is producing replies; the CRM's per-school WhatsApp status and outcomes are already shaped for it.

## Deploying (Vercel + Turso)

Deploy this as a **new Vercel project** with **Root Directory = `africa`**, so the live Kenya site (repo root) is not affected.

```bash
python3 -m africacrm publish                  # writes data/publish.db
turso db create africa-schools --from-file data/publish.db
turso db tokens create africa-schools
```

Environment variables (names only): `APP_PASSWORD`, `SECRET_KEY`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `PUBLIC_URL` (for unsubscribe links), `CRON_SECRET`. The app refuses to open the old Kenya or Sierra Leone databases, so it can't write over them by mistake.

On Vercel nothing runs in the background, so sending happens while the CRM is open in a browser tab, or on a schedule: call `POST /api/cron` with `Authorization: Bearer $CRON_SECRET` every 5–10 minutes (Vercel Cron on Pro, or any free cron service). Each call sends what is due and checks one inbox.

## Data protection

The country data names head teachers and officials, so it stays out of this public repository (`dataset/` and `data/` are git-ignored). Mailbox passwords are stored in your database only, never in the repo. Every email has an unsubscribe link, and anyone who asks to stop is never contacted again.

## Tests

```bash
python3 -m unittest discover tests
```
