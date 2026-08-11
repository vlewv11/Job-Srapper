from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .. import config, db
from ..scraping import scheduler
from . import render


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if os.getenv("AUTO_SCRAPE") == "1":
        task = asyncio.create_task(
            scheduler.run_forever(config.SCRAPE_INTERVAL_MINUTES)
        )
    try:
        yield
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="ML/AI Job Board", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    with db.connect() as conn:
        return HTMLResponse(render.render_index(conn))


@app.get("/healthz")
def healthz() -> dict:
    with db.connect() as conn:
        meta = db.stats(conn)
    return {
        "status": "ok",
        "now": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "vacancies": meta["total"],
        "last_scraped": meta["last_scraped"],
        "retention_days": config.RETENTION_DAYS,
        "interval_minutes": config.SCRAPE_INTERVAL_MINUTES,
        "auto_scrape": os.getenv("AUTO_SCRAPE") == "1",
    }
