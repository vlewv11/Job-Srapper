# job-scrapper

Scrapes ML / AI / LLM **Engineer / Researcher** vacancies (and derivatives)
from Telegram channels, filters them with regex (Russian + English), stores
them in SQLite, and publishes a dark dashboard.

It runs itself: **every 10 minutes** it pulls only what was posted since the
last cycle, and **posts older than 30 days are deleted** from the database.

```
   every 10 min
        │
Telegram channels ──▶ scraper (Telethon) ──▶ regex parser ──▶ SQLite ──▶ dashboard
                          ▲                                     │           (live or static)
                          └── per-channel watermark ────────────┘
                                                     30-day retention prune
```

## Setup

1. **Install deps** (managed by [uv](https://docs.astral.sh/uv/)):
   ```bash
   uv sync
   ```

2. **Telegram API credentials.** Go to <https://my.telegram.org> → *API
   development tools* → create an app. Copy `api_id` and `api_hash`:
   ```bash
   cp .env.example .env
   # edit .env and paste TG_API_ID / TG_API_HASH
   ```

3. **Channels.** List the channels you follow in `channels.txt`
   (one per line — `@name`, `t.me/name`, or a full URL). You must already be a
   member of any private channel.

4. **Log in once** (interactive — enter your phone + the code Telegram sends).
   A session file is saved under `data/` so later runs are non-interactive:
   ```bash
   uv run python main.py login
   ```

5. **Fill the database** with the last 30 days, once:
   ```bash
   uv run python main.py backfill --days 30
   ```

## Usage

```bash
# Serve the dashboard AND auto-scrape every 10 minutes (the normal way to run it):
uv run python main.py run                  # http://127.0.0.1:9000
uv run python main.py run --interval 5     # different cadence
uv run python main.py run --no-scrape      # dashboard only

# One cycle by hand (this is what the GitHub Action runs):
uv run python main.py scrape               # incremental + prune
uv run python main.py scrape --full        # ignore watermarks, re-read the window

# One-off maintenance / debugging:
uv run python main.py backfill --days 30   # full re-read of a window
uv run python main.py prune                # drop everything older than 30 days
uv run python main.py build                # export the static site to site/
uv run python main.py parse "Senior LLM Engineer, remote, $150k/year"
uv run python main.py session              # print the TG_SESSION secret for CI
```

Settings are environment variables (`.env` works): `SCRAPE_INTERVAL_MINUTES`
(default `10`), `RETENTION_DAYS` (default `30`), `DB_PATH`, `SITE_DIR`,
`CHANNELS_FILE`.

## Smart (incremental) scraping

Every message Telegram returns carries its id and post time, and messages come
back newest-first — so a cycle never downloads the whole history:

- each channel stores a **watermark** (`channel_state.last_message_id`), and
  the next cycle asks Telegram only for messages *after* it;
- iteration **stops at the first post older than the window**, so nothing
  beyond retention is ever fetched;
- the watermark only moves forward, and only when a channel was walked
  end-to-end — a flood-wait or a dropped connection re-reads instead of
  skipping;
- a cycle ends with the retention prune, so **posts older than 30 days are
  deleted automatically**.

A full 30-day backfill reads ~1500 posts across 14 channels; the incremental
cycle that follows reads 0 and finishes in seconds.

## Dashboard

Three time filters — **Today / 7 days / 30 days** — plus a channel picker and
full-text search. Filtering happens in the browser over the whole retention
window, so the page is instant, shareable (`?range=30d&channel=…&q=…`) and
identical whether it is served by FastAPI or as a static file. Timestamps are
rendered client-side, so a page built an hour ago still says "1h ago".

`GET /healthz` reports row count, last scrape time and the active settings.

## Deploying free on GitHub Pages

`.github/workflows/scrape-deploy.yml` is the whole deployment: a `*/10` cron
scrapes, prunes, rebuilds the static site and publishes it to
`https://<user>.github.io/<repo>/`.

1. **Settings → Pages → Source: GitHub Actions.**
2. **Settings → Secrets and variables → Actions**, add:
   | Secret | Value |
   |---|---|
   | `TG_API_ID`   | from my.telegram.org |
   | `TG_API_HASH` | from my.telegram.org |
   | `TG_SESSION`  | output of `uv run python main.py session` |
3. Push to `master`. The workflow can also be started by hand from the
   **Actions** tab (with optional `full` / `days` inputs).

`TG_SESSION` is an exported Telethon *string session* — CI has no session file
of its own. It is a login credential: keep it in Actions secrets only, and
re-run `main.py session` if you ever revoke the session in Telegram.

**How state survives between runs.** The SQLite file is force-pushed to a
parentless `state` branch after every successful cycle and restored at the
start of the next one, so watermarks and vacancies persist while that branch's
history never grows. The branch is machine-managed — don't commit to it.

**Worth knowing.**

- Keep the repo **public**: Pages and Actions minutes are free there. On a
  private repo a `*/10` cron would exhaust the free Actions minutes in days.
- GitHub's cron is best-effort — a run can be delayed or skipped when the
  runner pool is busy, and **scheduled workflows are disabled after 60 days
  without repository activity**.
- Every deployed page is public. Only publish channels you are comfortable
  republishing.
- If Telegram fails, the step is non-fatal: the previous data is redeployed and
  the next cycle catches up.

`.github/workflows/ci.yml` runs the test suite on every push and pull request.

## How matching works

A message is kept only if it advertises a real ML/AI/LLM role — a **domain**
term (`ML`, `AI`, `LLM`, `NLP`, `машинное обучение`, `искусственный интеллект`, …)
sitting next to a **role** noun (`engineer`, `researcher`, `scientist`,
`architect`, `инженер`, `разработчик`, `исследователь`, …), or a strong
standalone title (`Data Scientist`, `Applied Scientist`, `MLOps Engineer`,
`Head of AI`, …). Postings that only *mention* ML in passing (e.g. a Go backend
role) are dropped.

The parser also filters out non-vacancies:

- **Course / webinar / paid ads** (`erid=` ad token, "Открытый урок", OTUS,
  meetups, `#ads` channel promos) — internships and perk-mentions are kept.
- **Candidate / CV posts** (people seeking work: `#cv`, "ищу работу",
  "open to work", "looking for an internship").
- **CV topics in forum channels** — a supergroup topic titled *CV / resume /
  резюме* is skipped whole (its title is read from the topic's root message).
- **Investment / funding figures** (`Инвестиции — $300M`, "привлёк $152 млн")
  are never mistaken for salary.

**Multiple vacancies per post** are supported: numbered lists (`1)… 2)…`) and
"digest" posts are split into one row each; trailing channel-promo footers are
trimmed off.

All vocabulary lives at the top of [`src/scraping/patterns.py`](src/scraping/patterns.py) — add
the terms your channels actually use to tune precision/recall. Field extraction
(title / company / salary / location) prefers explicit labels (`Salary:`,
`Локация:`) and falls back to currency/keyword heuristics, so it is best-effort
by nature. **Contact** is pulled from the post (email, `@handle`, or `t.me/...`
link); if the post has none, it falls back to the poster's Telegram account
(signature, sender username, or the channel handle).

## Layout

```
main.py                     CLI: login · session · scrape · backfill · prune · build · run · parse
channels.txt                the channels to read
data/                       local state, never committed (vacancies.db, job_scraper.session)
src/
├── config.py               settings (interval, retention, paths) from the environment
├── db.py                   SQLite schema, dedup upsert, watermarks, retention prune
├── scraping/
│   ├── patterns.py         regex matching + field extraction (the part to tune)
│   ├── telegram.py         Telethon reader — incremental window + CV-topic skip
│   └── scheduler.py        the every-10-minutes loop
└── web/
    ├── app.py              FastAPI app (`/`, `/healthz`)
    ├── render.py           page model shared by the live and static dashboards
    ├── build.py            static export for GitHub Pages
    └── templates/          dashboard HTML + client-side filtering
tests/                      uv run pytest
.github/workflows/          ci.yml (tests) · scrape-deploy.yml (cron → Pages)
```

The code carries no comments by design — the README is the documentation.

Deduplication is by `(channel, message_id, slot)` — re-scraping an overlapping
window refreshes a post's rows instead of duplicating them (`slot` distinguishes
multiple vacancies from the same post).
