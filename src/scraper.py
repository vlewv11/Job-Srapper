from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import ChannelPrivateError, FloodWaitError, UsernameNotOccupiedError
from telethon.tl.types import User

from . import db, patterns

load_dotenv()

SESSION = str(Path(__file__).resolve().parent.parent / "job_scraper.session")
CHANNELS_FILE = Path(__file__).resolve().parent.parent / "channels.txt"

# In a forum (topic) channel, skip whole topics whose title looks like a
# CV / resume / job-seeker thread rather than a vacancies thread.
EXCLUDE_TOPIC_RE = re.compile(
    r"\b(cv|resume|резюме|кандидат|ищу\s*работ|open\s*to\s*work|job\s*seeker)\b",
    re.IGNORECASE,
)


def load_channels(path: Path | str = CHANNELS_FILE) -> list[str]:
    path = Path(path)
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


def client_from_env() -> TelegramClient:
    api_id = os.getenv("TG_API_ID")
    api_hash = os.getenv("TG_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit(
            "Missing TG_API_ID / TG_API_HASH. Copy .env.example to .env and fill "
            "in the credentials from https://my.telegram.org (API development tools)."
        )
    return TelegramClient(SESSION, int(api_id), api_hash)


def _message_url(channel: str, entity, message_id: int) -> str:
    username = getattr(entity, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"
    return f"https://t.me/c/{getattr(entity, 'id', channel)}/{message_id}"


async def _topic_excluded(client, entity, msg, cache: dict[int, str]) -> bool:
    """True if a forum message belongs to a CV/job-seeker topic."""
    r = getattr(msg, "reply_to", None)
    if r is None:
        return False
    tid = getattr(r, "reply_to_top_id", None) or getattr(r, "reply_to_msg_id", None)
    if not tid:
        return False
    if tid not in cache:
        try:
            root = await client.get_messages(entity, ids=tid)
            act = getattr(root, "action", None) if root else None
            cache[tid] = getattr(act, "title", "") or ""
        except Exception:
            cache[tid] = ""
    return bool(EXCLUDE_TOPIC_RE.search(cache[tid]))


async def _author_contact(client, msg, entity) -> str | None:
    try:
        sender = await msg.get_sender()
    except Exception:
        sender = None

    if isinstance(sender, User) and sender.username:
        return "@" + sender.username
    if getattr(msg, "post_author", None):
        return msg.post_author
    if isinstance(sender, User):
        name = " ".join(filter(None, [sender.first_name, sender.last_name]))
        return name or f"id{sender.id}"
    if getattr(entity, "username", None):
        return "@" + entity.username
    return None


async def scrape(
    days: int = 7,
    channels: list[str] | None = None,
    limit_per_channel: int = 3000,
    verbose: bool = True,
) -> dict:
    channels = channels or load_channels()
    if not channels:
        raise SystemExit(
            f"No channels configured. Add channel handles to {CHANNELS_FILE}."
        )

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    now_iso = datetime.now(timezone.utc).isoformat()
    counts = {"scanned": 0, "matched": 0, "messages": 0, "channels": 0,
              "topic_skipped": 0, "promo_skipped": 0}

    client = client_from_env()
    await client.start()

    with db.connect() as conn:
        for channel in channels:
            try:
                entity = await client.get_entity(channel)
            except (UsernameNotOccupiedError, ValueError):
                if verbose:
                    print(f"  ! skip {channel!r}: not found")
                continue
            except ChannelPrivateError:
                if verbose:
                    print(f"  ! skip {channel!r}: private / not a member")
                continue

            counts["channels"] += 1
            is_forum = bool(getattr(entity, "forum", False))
            topic_titles: dict[int, str] = {}
            ch_matched = 0
            try:
                async for msg in client.iter_messages(
                    entity, offset_date=None, limit=limit_per_channel
                ):
                    if msg.date and msg.date < cutoff:
                        break
                    text = msg.message or ""
                    if not text.strip():
                        continue

                    if is_forum and await _topic_excluded(client, entity, msg, topic_titles):
                        counts["topic_skipped"] += 1
                        continue

                    counts["scanned"] += 1

                    if patterns.is_promo(text):
                        counts["promo_skipped"] += 1
                        continue

                    vacs = patterns.parse_all(text)
                    if not vacs:
                        continue

                    counts["matched"] += len(vacs)
                    counts["messages"] += 1
                    ch_matched += len(vacs)

                    posted = msg.date.astimezone(timezone.utc).isoformat()
                    url = _message_url(channel, entity, msg.id)
                    author = None  # resolved once per message, only if needed
                    db.delete_message(conn, channel, msg.id)
                    for slot, vac in enumerate(vacs):
                        contact = vac.contact
                        if not contact:
                            if author is None:
                                author = await _author_contact(client, msg, entity) or ""
                            contact = author or None
                        db.insert(conn, {
                            "channel": channel,
                            "message_id": msg.id,
                            "slot": slot,
                            "posted_at": posted,
                            "title": vac.title,
                            "company": vac.company,
                            "salary": vac.salary,
                            "location": vac.location,
                            "remote": int(vac.remote),
                            "contact": contact,
                            "url": url,
                            "raw_text": text,
                            "scraped_at": now_iso,
                        })
            except FloodWaitError as e:
                print(f"  ! flood-wait {e.seconds}s on {channel!r}; stopping early")
                break

            if verbose:
                print(f"  · {channel}: {ch_matched} matched")

    await client.disconnect()
    return counts
