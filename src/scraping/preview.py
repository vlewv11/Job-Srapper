from __future__ import annotations

import asyncio
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

from .. import config, db
from . import ingest

BASE_URL = "https://t.me/s/{channel}"
PAGE_POSTS = 20
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
MAX_PAGES = 50

_VOID_TAGS = frozenset({
    "br", "img", "hr", "input", "meta", "link", "area",
    "base", "col", "embed", "source", "track", "wbr",
})

_MESSAGE = "tgme_widget_message"
_TEXT = "tgme_widget_message_text"
_DATE = "tgme_widget_message_date"
_AUTHOR = frozenset({
    "tgme_widget_message_from_author", "tgme_widget_message_author_name",
})
_NOT_BODY = frozenset({
    "tgme_widget_message_link_preview",
    "tgme_widget_message_reply",
    "tgme_widget_message_forwarded_from",
    "tgme_widget_message_poll",
    "tgme_widget_message_footer",
    "tgme_widget_message_reactions",
})


class PreviewUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Post:
    channel: str
    id: int
    date: datetime | None
    text: str
    author: str | None = None

    @property
    def url(self) -> str:
        return f"https://t.me/{self.channel}/{self.id}"


def _delay() -> float:
    raw = (os.getenv("PREVIEW_DELAY_SECONDS") or "").strip()
    try:
        return max(0.0, float(raw)) if raw else 1.0
    except ValueError:
        return 1.0


class _PageParser(HTMLParser):
    def __init__(self, channel: str):
        super().__init__(convert_charrefs=True)
        self.channel = channel
        self.posts: list[Post] = []
        self._stack: list[str] = []
        self._post: dict | None = None
        self._post_level = 0
        self._text_level = 0
        self._skip_level = 0
        self._date_level = 0
        self._author_level = 0

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            if tag == "br" and self._text_level and not self._skip_level:
                self._post["text"].append("\n")
            return

        self._stack.append(tag)
        level = len(self._stack)
        attrs = dict(attrs)
        classes = frozenset((attrs.get("class") or "").split())

        if _MESSAGE in classes and attrs.get("data-post"):
            self._open_post(attrs["data-post"], level)
            return
        if self._post is None:
            return

        if _DATE in classes:
            self._date_level = level
        elif classes & _AUTHOR:
            self._author_level = level
        elif _TEXT in classes and not self._text_level and not self._post["text"]:
            self._text_level = level
        elif self._text_level and classes & _NOT_BODY and not self._skip_level:
            self._skip_level = level

        if tag == "time" and self._date_level and attrs.get("datetime"):
            self._post["date"] = attrs["datetime"]

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        elif tag in self._stack:
            while self._stack and self._stack.pop() != tag:
                pass
        else:
            return

        level = len(self._stack)
        for name in ("_text_level", "_skip_level", "_date_level", "_author_level"):
            if getattr(self, name) > level:
                setattr(self, name, 0)
        if self._post is not None and self._post_level > level:
            self._close_post()

    def handle_data(self, data):
        if self._post is None or self._skip_level:
            return
        if self._text_level:
            self._post["text"].append(data)
        elif self._author_level:
            self._post["author"].append(data)

    def _open_post(self, data_post: str, level: int) -> None:
        if self._post is not None:
            self._close_post()
        _, _, raw_id = data_post.rpartition("/")
        if not raw_id.isdigit():
            return
        self._post = {"id": int(raw_id), "date": None, "text": [], "author": []}
        self._post_level = level
        self._text_level = self._skip_level = 0
        self._date_level = self._author_level = 0

    def _close_post(self) -> None:
        post, self._post = self._post, None
        self._post_level = 0
        if post is None:
            return
        self.posts.append(Post(
            channel=self.channel,
            id=post["id"],
            date=_parse_date(post["date"]),
            text=_clean_text("".join(post["text"])),
            author=" ".join("".join(post["author"]).split()) or None,
        ))

    def close(self):
        super().close()
        if self._post is not None:
            self._close_post()


def _clean_text(raw: str) -> str:
    return raw.replace("\r\n", "\n").strip()


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def fetch_page(channel: str, before: int | None = None) -> str:
    url = BASE_URL.format(channel=channel)
    if before:
        url += f"?before={before}"
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en,ru;q=0.9",
    })

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                if "/s/" not in response.geturl():
                    raise PreviewUnavailable(
                        f"{channel}: no public web preview "
                        f"(redirected to {response.geturl()})"
                    )
                return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404, 410):
                raise PreviewUnavailable(f"{channel}: HTTP {exc.code}") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        if attempt < MAX_RETRIES - 1:
            time.sleep(_delay() * (2 ** attempt))
    raise ConnectionError(f"{channel}: preview unreachable ({last_error})") from last_error


def iter_posts(
    channel: str,
    *,
    min_id: int = 0,
    cutoff: datetime | None = None,
    max_pages: int = MAX_PAGES,
    fetch=fetch_page,
    sleep=time.sleep,
):
    before: int | None = None
    seen: set[int] = set()

    for page in range(max_pages):
        if page:
            sleep(_delay())
        parser = _PageParser(channel)
        parser.feed(fetch(channel, before))
        parser.close()
        batch = sorted(parser.posts, key=lambda p: p.id, reverse=True)
        if not batch:
            return

        for post in batch:
            if post.id in seen:
                continue
            seen.add(post.id)
            if post.id <= min_id:
                return
            if cutoff and post.date and post.date < cutoff:
                return
            yield post

        oldest = batch[-1].id
        if oldest <= min_id + 1:
            return
        if before is not None and oldest >= before:
            return
        before = oldest
    else:
        print(
            f"  ! {channel}: stopped at the {max_pages}-page cap "
            f"(~{max_pages * PAGE_POSTS} posts); rerun to continue further back"
        )


def scrape(
    days: int | None = None,
    channels: list[str] | None = None,
    full: bool = False,
    verbose: bool = True,
    counts: dict | None = None,
    unavailable: list[str] | None = None,
) -> dict:
    window_days = days or config.RETENTION_DAYS
    channels = channels if channels is not None else ingest.load_channels()
    if not channels:
        raise SystemExit(
            f"No channels configured. Add channel handles to {config.CHANNELS_FILE}."
        )

    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    now_iso = datetime.now(timezone.utc).isoformat()
    counts = counts if counts is not None else ingest.new_counts()

    with db.connect() as conn:
        for channel in channels:
            since_id = 0 if full else db.get_watermark(conn, channel)
            newest_id, newest_at = 0, None
            ch_matched = 0

            try:
                for post in iter_posts(channel, min_id=since_id, cutoff=cutoff):
                    if post.id > newest_id:
                        newest_id = post.id
                        newest_at = post.date.isoformat() if post.date else None
                    if not post.text.strip():
                        continue

                    vacs = ingest.select_vacancies(counts, post.text)
                    if not vacs:
                        continue

                    ingest.store_message(
                        conn,
                        channel=channel,
                        message_id=post.id,
                        posted_at=(post.date or datetime.now(timezone.utc)).isoformat(),
                        url=post.url,
                        text=post.text,
                        vacancies=vacs,
                        fallback_contact=post.author or f"@{channel}",
                        scraped_at=now_iso,
                    )
                    ingest.record_message(counts, len(vacs))
                    ch_matched += len(vacs)
            except PreviewUnavailable as exc:
                if unavailable is not None:
                    unavailable.append(channel)
                if verbose:
                    print(f"  ! skip {channel}: {exc}")
                continue
            except (ConnectionError, ValueError) as exc:
                counts["errors"] += 1
                print(f"  ! {channel}: {type(exc).__name__}: {exc}")
                continue

            counts["channels"] += 1
            ingest.finish_channel(
                conn, channel,
                newest_id=newest_id, newest_at=newest_at,
                since_id=since_id, run_at=now_iso,
            )
            if verbose:
                print(f"  · {channel}: {ch_matched} matched")

        counts["pruned"] += db.prune(conn, config.RETENTION_DAYS)

    return counts


async def scrape_async(**kwargs) -> dict:
    return await asyncio.to_thread(lambda: scrape(**kwargs))
