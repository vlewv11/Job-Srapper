from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .. import config, db
from . import patterns

COUNTER_KEYS = (
    "scanned", "matched", "messages", "channels",
    "topic_skipped", "promo_skipped", "pruned", "errors",
)


def new_counts() -> dict:
    return dict.fromkeys(COUNTER_KEYS, 0)


def load_channels(path: Path | str | None = None) -> list[str]:
    path = Path(path) if path else config.CHANNELS_FILE
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.replace("https://", "").replace("http://", "")
        line = line.replace("t.me/", "").lstrip("@")
        out.append(line)
    return out


def select_vacancies(counts: dict, text: str) -> list:
    counts["scanned"] += 1
    if patterns.is_promo(text):
        counts["promo_skipped"] += 1
        return []
    return patterns.parse_all(text)


def store_message(
    conn,
    *,
    channel: str,
    message_id: int,
    posted_at: str,
    url: str,
    text: str,
    vacancies,
    fallback_contact: str | None = None,
    scraped_at: str | None = None,
) -> int:
    scraped_at = scraped_at or datetime.now(timezone.utc).isoformat()
    db.delete_message(conn, channel, message_id)
    for slot, vac in enumerate(vacancies):
        db.insert(conn, {
            "channel": channel,
            "message_id": message_id,
            "slot": slot,
            "posted_at": posted_at,
            "title": vac.title,
            "company": vac.company,
            "salary": vac.salary,
            "location": vac.location,
            "remote": int(vac.remote),
            "contact": vac.contact or fallback_contact or None,
            "url": url,
            "raw_text": text,
            "scraped_at": scraped_at,
        })
    return len(vacancies)


def record_message(counts: dict, matched: int) -> None:
    counts["matched"] += matched
    counts["messages"] += 1


def finish_channel(
    conn,
    channel: str,
    *,
    newest_id: int,
    newest_at: str | None,
    since_id: int,
    run_at: str,
) -> None:
    if newest_id:
        db.set_watermark(conn, channel, newest_id, newest_at, run_at)
    else:
        db.set_watermark(conn, channel, since_id, None, run_at)
    conn.commit()
