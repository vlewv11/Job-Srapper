# job-scrapper

Scrapes ML / AI / LLM **Engineer / Researcher** vacancies (and derivatives)
from Telegram channels, filters them with regex (Russian + English), stores
them in SQLite, and serves a dark dashboard for browsing by time window.

```
Telegram channels ──▶ scraper (Telethon) ──▶ regex parser ──▶ SQLite ──▶ dashboard (FastAPI)
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
   A `.session` file is saved so later runs are non-interactive:
   ```bash
   uv run python main.py login
   ```

## Usage

```bash
# Scrape the last 7 days (default) or any window:
uv run python main.py scrape --days 7
uv run python main.py scrape --days 30

# Launch the dashboard at http://127.0.0.1:9000
uv run python main.py serve

# Debug the regex on a single message (no Telegram needed):
uv run python main.py parse "Senior LLM Engineer, remote, $150k/year"
```

The dashboard filters (time range **7d / 30d / 90d / All**, channel, remote-only,
and full-text search) are all URL query params, so any view is shareable.

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

All vocabulary lives at the top of [`src/patterns.py`](src/patterns.py) — add
the terms your channels actually use to tune precision/recall. Field extraction
(title / company / salary / location) prefers explicit labels (`Salary:`,
`Локация:`) and falls back to currency/keyword heuristics, so it is best-effort
by nature. **Contact** is pulled from the post (email, `@handle`, or `t.me/...`
link); if the post has none, it falls back to the poster's Telegram account
(signature, sender username, or the channel handle).

## Layout

| File | Role |
|------|------|
| `src/patterns.py`  | regex matching + field extraction (the part to tune) |
| `src/db.py`        | SQLite schema, dedup upsert, filtered queries |
| `src/scraper.py`   | Telethon channel reader + time window + CV-topic skip |
| `src/dashboard.py` | FastAPI app |
| `src/templates/`   | dashboard HTML |
| `main.py`          | CLI (`login` / `scrape` / `serve` / `parse`) |

Deduplication is by `(channel, message_id, slot)` — re-scraping an overlapping
window refreshes a post's rows instead of duplicating them (`slot` distinguishes
multiple vacancies from the same post).
