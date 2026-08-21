from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from .. import config


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


async def cycle(days: int | None = None, full: bool = False) -> dict | None:
    from .runner import run

    try:
        counts = await run(days=days, full=full, verbose=False)
    except Exception as exc:
        _log(f"scrape failed: {type(exc).__name__}: {exc}")
        return None
    _log(
        f"scraped {counts['channels']} channel(s): +{counts['matched']} vacancies "
        f"from {counts['messages']} new post(s), pruned {counts['pruned']}"
        + (f", {counts['errors']} error(s)" if counts["errors"] else "")
    )
    return counts


async def run_forever(interval_minutes: int | None = None) -> None:
    interval = (interval_minutes or config.SCRAPE_INTERVAL_MINUTES) * 60
    _log(
        f"auto-scrape every {interval // 60} min from {config.SCRAPE_SOURCE}, "
        f"keeping {config.RETENTION_DAYS} days"
    )
    while True:
        await cycle()
        await asyncio.sleep(interval)
