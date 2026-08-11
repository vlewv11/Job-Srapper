from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import config, db

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

RANGES = [
    {"key": "today", "label": "Today", "days": None},
    {"key": "7d", "label": "7 days", "days": 7},
    {"key": "30d", "label": "30 days", "days": 30},
]
DEFAULT_RANGE = "7d"

_SEARCH_TEXT_CHARS = 1200


def contact_href(contact: str | None) -> str | None:
    if not contact:
        return None
    if contact.startswith("@"):
        return f"https://t.me/{contact[1:]}"
    if contact.startswith("http"):
        return contact
    if "@" in contact and "." in contact.split("@")[-1]:
        return f"mailto:{contact}"
    return None


def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _row_view(row: sqlite3.Row) -> dict:
    posted = _iso(row["posted_at"])
    contact = row["contact"] or "—"
    haystack = " ".join(
        filter(None, [
            row["title"], row["company"], row["channel"], row["location"],
            row["salary"], row["contact"], (row["raw_text"] or "")[:_SEARCH_TEXT_CHARS],
        ])
    ).lower()
    return {
        "title": row["title"] or "Untitled role",
        "company": row["company"] or row["channel"],
        "channel": row["channel"],
        "salary": row["salary"] or "—",
        "location": row["location"] or "—",
        "remote": bool(row["remote"]),
        "contact": contact,
        "contact_href": contact_href(row["contact"]),
        "url": row["url"],
        "posted_at": row["posted_at"],
        "posted_ts": int(posted.timestamp() * 1000) if posted else 0,
        "posted_label": posted.strftime("%b %d") if posted else "—",
        "search": haystack,
    }


def build_context(conn: sqlite3.Connection) -> dict:
    rows = db.query(conn, days=config.RETENTION_DAYS)
    vacancies = [_row_view(r) for r in rows]
    return {
        "vacancies": vacancies,
        "count": len(vacancies),
        "ranges": RANGES,
        "default_range": DEFAULT_RANGE,
        "channels": sorted({v["channel"] for v in vacancies}),
        "retention_days": config.RETENTION_DAYS,
        "interval_minutes": config.SCRAPE_INTERVAL_MINUTES,
        "meta": db.stats(conn),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def render_html(context: dict) -> str:
    return _ENV.get_template("index.html").render(**context)


def render_index(conn: sqlite3.Connection) -> str:
    return render_html(build_context(conn))
