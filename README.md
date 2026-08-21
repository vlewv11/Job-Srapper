# job-scrapper

Scrapes ML / AI / LLM **Engineer / Researcher** vacancies (and derivatives)
from Telegram channels, filters them with regex (Russian + English), stores
them in SQLite, and publishes a dark dashboard.

It runs itself: **every 10 minutes** it pulls only what was posted since the
last cycle, and **posts older than 30 days are deleted** from the database.

**No Telegram account is required.** Public channels are read off their
`t.me/s/<name>` web preview, which Telegram serves to anyone. Credentials are
optional and only buy you the channels that have no such page.

```
   every 10 min
        │
        ├─▶ t.me/s/<channel>  (default — no credentials) ──┐
        │                                                  ├─▶ regex parser ──▶ SQLite ──▶ dashboard
        └─▶ MTProto/Telethon  (only for what has no        ─┘        │            (live or static)
             web preview; needs TG_SESSION)                          │
                          ▲                                          │
                          └── per-channel watermark ─────────────────┘
                                                     30-day retention prune
```

| Source | Credentials | Reaches | Fails when |
| --- | --- | --- | --- |
| `preview` | none | public channels | Telegram changes the preview markup |
| `telegram` | `TG_API_ID`, `TG_API_HASH`, `TG_SESSION` | everything you can see, groups included | the session is revoked |
| `auto` *(default)* | optional | public channels, plus the rest when credentials exist | — degrades to `preview` |

## Setup

1. **Install deps** (managed by [uv](https://docs.astral.sh/uv/)):
   ```bash
   uv sync
   ```

2. **Channels.** List them in `channels.txt` (one per line — `@name`,
   `t.me/name`, or a full URL).

3. **Fill the database** with the last 30 days, once:
   ```bash
   uv run python main.py backfill --days 30
   ```

That is the whole setup. The steps below are **optional**, and only needed for
channels that serve no public web preview — groups, and channels whose owner
turned the preview off. A cycle reports those by name and carries on without
them.

4. **Telegram API credentials.** <https://my.telegram.org> → *API development
   tools* → create an app, then:
   ```bash
   cp .env.example .env
   # edit .env and paste TG_API_ID / TG_API_HASH
   ```

5. **Log in once** (interactive — your phone plus the code Telegram sends).
   A session file lands in `data/`, so later runs are non-interactive:
   ```bash
   uv run python main.py login
   uv run python main.py session   # prints the string for the TG_SESSION secret
   ```

   ⚠️ A string session is a live key to your account. Use it in **one place at
   a time** — Telegram revokes an auth key it sees used from two IPs at once,
   which silently kills the MTProto pass until you re-issue it. Never commit it.

## Usage

```bash
# Serve the dashboard AND auto-scrape every 10 minutes (the normal way to run it):
uv run python main.py run                  # http://127.0.0.1:9000
uv run python main.py run --interval 5     # different cadence
uv run python main.py run --no-scrape      # dashboard only

# One cycle by hand (this is what the GitHub Action runs):
uv run python main.py scrape               # incremental + prune
uv run python main.py scrape --full        # ignore watermarks, re-read the window
uv run python main.py scrape --source preview   # web pages only, ignore any session
uv run python main.py scrape --source telegram  # MTProto only (needs TG_SESSION)

# One-off maintenance / debugging:
uv run python main.py backfill --days 30   # full re-read of a window
uv run python main.py prune                # drop everything older than 30 days
uv run python main.py build                # export the static site to site/
uv run python main.py parse "Senior LLM Engineer, remote, $150k/year"
uv run python main.py session              # print the TG_SESSION secret for CI
```

`scrape` and `backfill` exit non-zero when **no** channel could be read, so a
broken cycle is loud instead of publishing stale data. `--summary out.json`
writes the counters for a CI step to act on.

Settings are environment variables (`.env` works): `SCRAPE_SOURCE`
(default `auto`), `SCRAPE_INTERVAL_MINUTES` (default `10`), `RETENTION_DAYS`
(default `30`), `PREVIEW_DELAY_SECONDS` (default `1.0`), `DB_PATH`, `SITE_DIR`,
`CHANNELS_FILE`.

## Reading channels without an account

`https://t.me/s/<channel>` is a server-rendered page Telegram publishes for
every public channel: the newest 20 posts, each with its id, UTC timestamp and
full text, and `?before=<id>` walks backwards through history. That is
everything the parser needs, so the default cycle uses no API id, no api hash
and no session, and cannot be locked out by a revoked auth key.

`src/scraping/preview.py` parses those pages with `html.parser`, scoped to
`div.tgme_widget_message_text`. **That scoping is load-bearing:** Telegram renders
a link-preview card next to the body carrying the headline and summary of
whatever the post linked to, plus view counts and reactions. Letting any of that
into the text would invent vacancies out of news articles, so the parser reads
the body div and nothing else. Message text comes out byte-identical to
Telethon's `message` — verified against 136 posts the MTProto backend had
already stored, with zero differences.

Two things the preview cannot do: groups and preview-disabled channels serve a
redirect instead of a page (they need MTProto), and forum topics don't exist
there, so the CV-topic filter only applies to the MTProto pass.

## Smart (incremental) scraping

Both backends return posts newest-first with an id and a post time, so a cycle
never downloads the whole history:

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
cycle that follows reads 0 and finishes in seconds. On the preview backend the
watermark usually sits inside the newest page, so a quiet channel costs exactly
one HTTP request per cycle (`PREVIEW_DELAY_SECONDS` spaces them out).

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
2. Push to `master`. The workflow can also be started by hand from the
   **Actions** tab (with optional `full` / `days` / `source` inputs).

**No secrets are required.** The default `auto` source reads every public
channel off `t.me/s/`, which needs no credentials at all.

Only add secrets if your list includes channels with no public web preview:

   | Secret | Value |
   |---|---|
   | `TG_API_ID`   | from my.telegram.org |
   | `TG_API_HASH` | from my.telegram.org |
   | `TG_SESSION`  | output of `uv run python main.py session` |

`TG_SESSION` is an exported Telethon *string session* — CI has no session file
of its own — and it is a login credential to your account. Keep it in Actions
secrets only. Telegram revokes an auth key it sees used from more than one IP at
a time, so do not keep the same string in a local `.env` while CI is running;
re-issue it with `main.py session` when that happens.

**How state survives between runs.** The SQLite file is force-pushed to a
parentless `state` branch after every successful cycle and restored at the
start of the next one, so watermarks and vacancies persist while that branch's
history never grows. The branch is machine-managed — don't commit to it.

**Worth knowing.**

- Keep the repo **public**: Pages and Actions minutes are free there. On a
  private repo a `*/10` cron would exhaust the free Actions minutes in days.
- GitHub's cron is best-effort — `*/10` in practice lands closer to every
  20–40 minutes, a run can be dropped when the runner pool is busy or when the
  previous one is still inside the `scrape-deploy` concurrency group, and
  **scheduled workflows are disabled after 60 days without repository
  activity**.
- Every deployed page is public. Only publish channels you are comfortable
  republishing.
- **A cycle that reads nothing fails the run**, so the database is never
  persisted and the site is never rebuilt from a scrape that did not happen.
  A *partial* cycle still publishes — a channel that errored, or an MTProto pass
  skipped for a dead session, is reported as a `::warning::` annotation and in
  the run summary rather than failing everything. Do not wrap the scrape step in
  `continue-on-error`: that turns a broken cycle into a green run that keeps
  redeploying stale data.

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
│   ├── ingest.py           channel list, post → vacancy rows, watermarks (no Telethon)
│   ├── preview.py          t.me/s/ reader — the default, needs no credentials
│   ├── telegram.py         Telethon reader — groups, private channels, CV-topic skip
│   ├── runner.py           picks the backend, degrades instead of failing
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
