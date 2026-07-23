from __future__ import annotations

import argparse
import asyncio

from src import patterns


def cmd_login(_args):
    from src.scraper import client_from_env

    async def _run():
        client = client_from_env()
        await client.start()
        me = await client.get_me()
        print(f"Logged in as {me.first_name} (@{me.username}). Session saved.")
        await client.disconnect()

    asyncio.run(_run())


def cmd_scrape(args):
    from src.scraper import scrape

    print(f"Scraping last {args.days} day(s)…")
    counts = asyncio.run(scrape(days=args.days))
    print(
        f"\nDone. {args.days}d over {counts['channels']} channel(s): "
        f"scanned {counts['scanned']}, {counts['matched']} vacancies "
        f"from {counts['messages']} posts. "
        f"Skipped {counts['promo_skipped']} promo/course, "
        f"{counts['topic_skipped']} CV-topic."
    )


def cmd_serve(args):
    import uvicorn

    print(f"Dashboard → http://{args.host}:{args.port}")
    uvicorn.run("src.dashboard:app", host=args.host, port=args.port, reload=args.reload)


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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="job-scrapper",
        description="Scrape ML/AI/LLM vacancies from Telegram into SQLite + dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="one-time Telegram login").set_defaults(func=cmd_login)

    sp = sub.add_parser("scrape", help="scrape channels")
    sp.add_argument("--days", type=int, default=7, help="time window in days (default 7)")
    sp.set_defaults(func=cmd_scrape)

    sv = sub.add_parser("serve", help="run the dashboard")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=9000)
    sv.add_argument("--reload", action="store_true")
    sv.set_defaults(func=cmd_serve)

    pp = sub.add_parser("parse", help="classify one message (debug)")
    pp.add_argument("text")
    pp.set_defaults(func=cmd_parse)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
