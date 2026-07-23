from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import db

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

app = FastAPI(title="ML/AI Job Board")

RANGES = [("7d", 7), ("30d", 30), ("90d", 90), ("All", None)]


def _humanize(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    days = (datetime.now(timezone.utc) - dt).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days}d ago"
    return dt.strftime("%b %d")


def _contact_href(contact: str | None) -> str | None:
    if not contact:
        return None
    if contact.startswith("@"):
        return f"https://t.me/{contact[1:]}"
    if contact.startswith("http"):
        return contact
    if "@" in contact and "." in contact.split("@")[-1]:
        return f"mailto:{contact}"
    return None


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    days: int | None = Query(default=7),
    channel: str | None = Query(default=None),
    q: str | None = Query(default=None),
    remote: int = Query(default=0),
):
    with db.connect() as conn:
        rows = db.query(
            conn,
            days=days,
            channel=channel or None,
            search=(q or None),
            remote_only=bool(remote),
        )
        all_channels = db.channels(conn)
        meta = db.stats(conn)

    vacancies = [
        {
            "title": r["title"] or "Untitled role",
            "company": r["company"] or r["channel"],
            "salary": r["salary"] or "—",
            "location": r["location"] or "—",
            "remote": bool(r["remote"]),
            "contact": r["contact"] or "—",
            "contact_href": _contact_href(r["contact"]),
            "url": r["url"],
            "posted": _humanize(r["posted_at"]),
        }
        for r in rows
    ]

    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "vacancies": vacancies,
            "count": len(vacancies),
            "ranges": RANGES,
            "active_days": days,
            "channels": all_channels,
            "active_channel": channel or "",
            "query": q or "",
            "remote": bool(remote),
            "meta": meta,
        },
    )
