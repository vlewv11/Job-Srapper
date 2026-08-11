from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import ChannelPrivateError, FloodWaitError, UsernameNotOccupiedError
from telethon.sessions import StringSession
from telethon.tl.types import User

from .. import config, db
from . import patterns

EXCLUDE_TOPIC_RE = re.compile(
    r"\b(cv|resume|резюме|кандидат|ищу\s*работ|open\s*to\s*work|job\s*seeker)\b",
    re.IGNORECASE,
)


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


def client_from_env() -> TelegramClient:
    api_id = os.getenv("TG_API_ID")
    api_hash = os.getenv("TG_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit(
            "Missing TG_API_ID / TG_API_HASH. Copy .env.example to .env and fill "
            "in the credentials from https://my.telegram.org (API development tools)."
        )
    session_string = (os.getenv("TG_SESSION") or "").strip()
    if not session_string:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    session = StringSession(session_string) if session_string else config.SESSION_PATH
    return TelegramClient(session, int(api_id), api_hash)


async def connected_client() -> TelegramClient:
    client = client_from_env()
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise SystemExit(
            "Telegram session is missing or expired. Run `python main.py login` "
            "locally, then `python main.py session` to refresh the TG_SESSION secret."
        )
    return client


def _message_url(channel: str, entity, message_id: int) -> str:
    username = getattr(entity, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"
    return f"https://t.me/c/{getattr(entity, 'id', channel)}/{message_id}"


async def _topic_excluded(client, entity, msg, cache: dict[int, str]) -> bool:
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


async def scrape(
    days: int | None = None,
    channels: list[str] | None = None,
    full: bool = False,
    limit_per_channel: int = 3000,
    verbose: bool = True,
) -> dict:
    window_days = days or config.RETENTION_DAYS
    channels = channels or load_channels()
    if not channels:
        raise SystemExit(
            f"No channels configured. Add channel handles to {config.CHANNELS_FILE}."
        )

    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    now_iso = datetime.now(timezone.utc).isoformat()
    counts = {"scanned": 0, "matched": 0, "messages": 0, "channels": 0,
              "topic_skipped": 0, "promo_skipped": 0, "pruned": 0}

    client = await connected_client()

    try:
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
                since_id = 0 if full else db.get_watermark(conn, channel)
                is_forum = bool(getattr(entity, "forum", False))
                topic_titles: dict[int, str] = {}
                ch_matched = 0
                newest_id, newest_at = 0, None
                completed = True

                try:
                    async for msg in client.iter_messages(
                        entity, limit=limit_per_channel, min_id=since_id
                    ):
                        if msg.id > newest_id:
                            newest_id = msg.id
                            newest_at = (
                                msg.date.astimezone(timezone.utc).isoformat()
                                if msg.date else None
                            )
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

                        fallback = None
                        if any(not v.contact for v in vacs):
                            fallback = await _author_contact(client, msg, entity)

                        store_message(
                            conn,
                            channel=channel,
                            message_id=msg.id,
                            posted_at=msg.date.astimezone(timezone.utc).isoformat(),
                            url=_message_url(channel, entity, msg.id),
                            text=text,
                            vacancies=vacs,
                            fallback_contact=fallback,
                            scraped_at=now_iso,
                        )
                        counts["matched"] += len(vacs)
                        counts["messages"] += 1
                        ch_matched += len(vacs)
                except FloodWaitError as e:
                    completed = False
                    print(f"  ! flood-wait {e.seconds}s on {channel!r}; stopping early")

                if completed and newest_id:
                    db.set_watermark(conn, channel, newest_id, newest_at, now_iso)
                elif completed:
                    db.set_watermark(conn, channel, since_id, None, now_iso)
                conn.commit()

                if verbose:
                    print(f"  · {channel}: {ch_matched} matched")

                if not completed:
                    break

            counts["pruned"] = db.prune(conn, config.RETENTION_DAYS)
    finally:
        await client.disconnect()

    return counts
