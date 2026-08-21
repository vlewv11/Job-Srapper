from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from src import config
from src.scraping import patterns
from src.scraping.runner import SOURCES


def _write_summary(path: str | None, counts: dict) -> None:
    if not path:
        return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(counts, fh, indent=1, sort_keys=True)


def _report(counts: dict) -> int:
    print(
        f"\nDone. {counts['channels']} channel(s): scanned {counts['scanned']} new "
        f"post(s), stored {counts['matched']} vacancies from {counts['messages']} "
        f"post(s). Skipped {counts['promo_skipped']} promo/course, "
        f"{counts['topic_skipped']} CV-topic. Pruned {counts['pruned']} expired."
    )
    if counts["errors"]:
        print(f"{counts['errors']} channel(s) errored.")
    if not counts["channels"]:
        print(
            "No channel was read. Nothing was stored, so the database is unchanged.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_login(args):
    from src.scraping.telegram import client_from_env

    async def _run():
        client = client_from_env()
        await client.start()
        me = await client.get_me()
        print(f"Logged in as {me.first_name} (@{me.username}). Session saved.")
        await client.disconnect()

    asyncio.run(_run())


def cmd_session(args):
    from telethon.sessions import StringSession

    from src.scraping.telegram import connected_client

    async def _run():
        client = await connected_client()
        try:
            print(StringSession.save(client.session))
        finally:
            await client.disconnect()

    asyncio.run(_run())


def cmd_scrape(args):
    from src.scraping import runner

    days = args.days or config.RETENTION_DAYS
    mode = "full" if args.full else "incremental"
    source = runner.resolve_source(args.source)
    print(f"Scraping ({mode}, window {days}d, source {source})…")
    counts = asyncio.run(runner.run(days=days, full=args.full, source=source))
    _write_summary(args.summary, counts)
    return _report(counts)


def cmd_backfill(args):
    from src.scraping import runner

    source = runner.resolve_source(args.source)
    print(f"Backfilling the last {args.days} day(s) from scratch (source {source})…")
    counts = asyncio.run(runner.run(days=args.days, full=True, source=source))
    _write_summary(args.summary, counts)
    return _report(counts)


def cmd_prune(args):
    from src import db

    days = args.days or config.RETENTION_DAYS
    with db.connect() as conn:
        removed = db.prune(conn, days)
        left = db.stats(conn)["total"]
    print(f"Deleted {removed} vacancy row(s) older than {days}d; {left} left.")


def cmd_build(args):
    from src.web.build import build_site

    out = build_site(args.out)
    print(f"Static site → {out / 'index.html'}")


def cmd_run(args):
    import uvicorn

    os.environ["AUTO_SCRAPE"] = "0" if args.no_scrape else "1"
    if args.source:
        os.environ["SCRAPE_SOURCE"] = args.source
        config.SCRAPE_SOURCE = args.source
    if args.interval:
        os.environ["SCRAPE_INTERVAL_MINUTES"] = str(args.interval)
        config.SCRAPE_INTERVAL_MINUTES = args.interval
    print(
        f"Dashboard → http://{args.host}:{args.port}  "
        f"(auto-scrape every {config.SCRAPE_INTERVAL_MINUTES} min from "
        f"{config.SCRAPE_SOURCE}, keeping {config.RETENTION_DAYS} days)"
    )
    uvicorn.run("src.web.app:app", host=args.host, port=args.port)


def cmd_parse(args):
    vacs = patterns.parse_all(args.text)
    if not vacs:
        print("Not a relevant vacancy.")
        return
    for i, vac in enumerate(vacs):
        if len(vacs) > 1:
            print(f"--- vacancy {i + 1}/{len(vacs)} ---")
        for k, v in patterns.as_dict(vac).items():
            print(f"  {k:9}: {v}")


def _add_summary(parser) -> None:
    parser.add_argument(
        "--summary", default=None,
        help="write the cycle counters to this path as JSON",
    )


def _add_source(parser) -> None:
    parser.add_argument(
        "--source", choices=SOURCES, default=None,
        help=(
            "preview = t.me/s/ web pages, no credentials; telegram = MTProto, needs "
            f"a session; auto = preview then MTProto for the rest "
            f"(default {config.SCRAPE_SOURCE})"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="job-scrapper",
        description=(
            "Auto-scrape ML/AI/LLM vacancies from Telegram into SQLite "
            f"(every {config.SCRAPE_INTERVAL_MINUTES} min, keeping "
            f"{config.RETENTION_DAYS} days) + dashboard"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="one-time Telegram login").set_defaults(func=cmd_login)
    sub.add_parser(
        "session", help="print the string session for the TG_SESSION secret"
    ).set_defaults(func=cmd_session)

    sp = sub.add_parser("scrape", help="run one scrape cycle (incremental + prune)")
    sp.add_argument("--days", type=int, default=None,
                    help=f"window in days (default {config.RETENTION_DAYS})")
    sp.add_argument("--full", action="store_true",
                    help="ignore watermarks and re-read the whole window")
    _add_source(sp)
    _add_summary(sp)
    sp.set_defaults(func=cmd_scrape)

    bf = sub.add_parser("backfill", help="one-off full scrape of the last N days")
    bf.add_argument("--days", type=int, default=config.RETENTION_DAYS)
    _add_source(bf)
    _add_summary(bf)
    bf.set_defaults(func=cmd_backfill)

    pr = sub.add_parser("prune", help="delete vacancies past the retention window")
    pr.add_argument("--days", type=int, default=None)
    pr.set_defaults(func=cmd_prune)

    bl = sub.add_parser("build", help="export the static site (for GitHub Pages)")
    bl.add_argument("--out", default=None, help=f"output dir (default {config.SITE_DIR})")
    bl.set_defaults(func=cmd_build)

    rn = sub.add_parser("run", help="serve the dashboard and auto-scrape in the background")
    rn.add_argument("--host", default="127.0.0.1")
    rn.add_argument("--port", type=int, default=9000)
    rn.add_argument("--interval", type=int, default=None,
                    help=f"minutes between scrapes (default {config.SCRAPE_INTERVAL_MINUTES})")
    rn.add_argument("--no-scrape", action="store_true", help="serve only, do not scrape")
    _add_source(rn)
    rn.set_defaults(func=cmd_run)

    pp = sub.add_parser("parse", help="classify one message (debug)")
    pp.add_argument("text")
    pp.set_defaults(func=cmd_parse)

    return p


def main():
    args = build_parser().parse_args()
    raise SystemExit(args.func(args) or 0)


if __name__ == "__main__":
    main()
