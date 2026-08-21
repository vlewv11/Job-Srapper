from __future__ import annotations

import asyncio

from src.scraping import runner, scheduler


def test_cycle_returns_counts(monkeypatch):
    seen = {}

    async def fake_run(days=None, full=False, verbose=True):
        seen.update(days=days, full=full)
        return {"channels": 1, "matched": 2, "messages": 1, "pruned": 3,
                "scanned": 4, "topic_skipped": 0, "promo_skipped": 0, "errors": 0}

    monkeypatch.setattr(runner, "run", fake_run)
    counts = asyncio.run(scheduler.cycle())

    assert counts["matched"] == 2
    assert seen == {"days": None, "full": False}


def test_cycle_survives_a_scrape_failure(monkeypatch, capsys):
    async def boom(**kwargs):
        raise ConnectionError("telegram unreachable")

    monkeypatch.setattr(runner, "run", boom)

    assert asyncio.run(scheduler.cycle()) is None
    assert "telegram unreachable" in capsys.readouterr().out


def test_run_forever_ticks_on_the_interval(monkeypatch):
    calls, sleeps = [], []

    async def fake_cycle(*a, **kw):
        calls.append(1)
        if len(calls) == 3:
            raise asyncio.CancelledError
        return {}

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(scheduler, "cycle", fake_cycle)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def drive():
        try:
            await scheduler.run_forever(10)
        except asyncio.CancelledError:
            pass

    asyncio.run(drive())
    assert sleeps == [600, 600]
