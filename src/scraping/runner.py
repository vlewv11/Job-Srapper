from __future__ import annotations

import os

from . import ingest, preview

SOURCES = ("auto", "preview", "telegram")

TELEGRAM_ENV = ("TG_API_ID", "TG_API_HASH", "TG_SESSION")


def resolve_source(source: str | None = None) -> str:
    from .. import config

    choice = (source or config.SCRAPE_SOURCE or "auto").strip().lower()
    return choice if choice in SOURCES else "auto"


def telegram_configured() -> bool:
    return all((os.getenv(name) or "").strip() for name in TELEGRAM_ENV)


async def run(
    days: int | None = None,
    full: bool = False,
    source: str | None = None,
    channels: list[str] | None = None,
    verbose: bool = True,
) -> dict:
    source = resolve_source(source)
    counts = ingest.new_counts()

    if source == "telegram":
        from . import telegram

        return await telegram.scrape(
            days=days, full=full, channels=channels, verbose=verbose, counts=counts
        )

    unavailable: list[str] = []
    await preview.scrape_async(
        days=days, full=full, channels=channels, verbose=verbose,
        counts=counts, unavailable=unavailable,
    )

    if unavailable and source == "auto":
        await _mtproto_pass(unavailable, days, full, verbose, counts)
    elif unavailable:
        print(
            f"  ! no web preview for {', '.join(unavailable)} — "
            f"read those with --source auto and a Telegram session"
        )

    return counts


async def _mtproto_pass(
    channels: list[str],
    days: int | None,
    full: bool,
    verbose: bool,
    counts: dict,
) -> None:
    listed = ", ".join(channels)
    if not telegram_configured():
        missing = [n for n in TELEGRAM_ENV if not (os.getenv(n) or "").strip()]
        print(
            f"  ! no web preview for {listed}; skipping them "
            f"({' / '.join(missing)} not set)"
        )
        return

    from . import telegram

    print(f"  → {listed}: no web preview, falling back to MTProto")
    try:
        await telegram.scrape(
            days=days, full=full, channels=channels, verbose=verbose, counts=counts
        )
    except SystemExit as exc:
        counts["errors"] += 1
        print(f"  ! MTProto pass skipped: {exc}")
    except Exception as exc:
        counts["errors"] += 1
        print(f"  ! MTProto pass failed: {type(exc).__name__}: {exc}")
