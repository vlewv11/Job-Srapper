from __future__ import annotations

import asyncio

import pytest

from src import config
from src.scraping import ingest, preview, runner, telegram

CREDENTIALS = {"TG_API_ID": "1", "TG_API_HASH": "h", "TG_SESSION": "s"}


@pytest.fixture
def no_credentials(monkeypatch):
    for name in runner.TELEGRAM_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def credentials(monkeypatch):
    for name, value in CREDENTIALS.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def fake_preview(monkeypatch):
    calls: list[dict] = []

    def install(*, matched=1, channels=1, unavailable_channels=()):
        def fake_scrape(**kwargs):
            calls.append(kwargs)
            counts = kwargs["counts"]
            counts["matched"] += matched
            counts["channels"] += channels
            if kwargs.get("unavailable") is not None:
                kwargs["unavailable"].extend(unavailable_channels)
            return counts

        monkeypatch.setattr(preview, "scrape", fake_scrape)
        return calls

    return install


@pytest.fixture
def fake_telegram(monkeypatch):
    calls: list[dict] = []

    def install(effect=None, matched=0):
        async def fake_scrape(**kwargs):
            calls.append(kwargs)
            if effect is not None:
                raise effect
            kwargs["counts"]["matched"] += matched
            kwargs["counts"]["channels"] += 1
            return kwargs["counts"]

        monkeypatch.setattr(telegram, "scrape", fake_scrape)
        return calls

    return install


def run(**kwargs):
    return asyncio.run(runner.run(verbose=False, **kwargs))


# --- source resolution -----------------------------------------------------

def test_resolve_source_prefers_the_explicit_choice():
    assert runner.resolve_source("preview") == "preview"
    assert runner.resolve_source("TELEGRAM") == "telegram"


def test_resolve_source_falls_back_to_the_configured_default(monkeypatch):
    monkeypatch.setattr(config, "SCRAPE_SOURCE", "preview")
    assert runner.resolve_source(None) == "preview"


def test_resolve_source_rejects_nonsense(monkeypatch):
    monkeypatch.setattr(config, "SCRAPE_SOURCE", "auto")
    assert runner.resolve_source("carrier-pigeon") == "auto"


def test_the_shipped_default_needs_no_session():
    assert config.SCRAPE_SOURCE in ("auto", "preview")


# --- routing ---------------------------------------------------------------

def test_preview_only_never_touches_telegram(credentials, fake_preview, fake_telegram):
    fake_preview(unavailable_channels=("groupchat",))
    tg = fake_telegram()

    counts = run(source="preview")

    assert counts["matched"] == 1
    assert tg == []


def test_telegram_only_never_touches_the_preview(fake_preview, fake_telegram):
    pv = fake_preview()
    tg = fake_telegram(matched=3)

    counts = run(source="telegram")

    assert counts["matched"] == 3
    assert pv == []
    assert len(tg) == 1


def test_auto_hands_preview_less_channels_to_mtproto(
    credentials, fake_preview, fake_telegram
):
    fake_preview(matched=5, unavailable_channels=("cyprusithr", "prog_itjobs"))
    tg = fake_telegram(matched=2)

    counts = run(source="auto")

    assert len(tg) == 1
    assert tg[0]["channels"] == ["cyprusithr", "prog_itjobs"]
    assert counts["matched"] == 7


def test_auto_skips_the_mtproto_pass_when_everything_is_public(
    credentials, fake_preview, fake_telegram
):
    fake_preview()
    tg = fake_telegram()

    run(source="auto")

    assert tg == []


def test_auto_explains_itself_when_credentials_are_missing(
    no_credentials, fake_preview, fake_telegram, capsys
):
    fake_preview(unavailable_channels=("cyprusithr",))
    tg = fake_telegram()

    counts = run(source="auto")

    out = capsys.readouterr().out
    assert "cyprusithr" in out and "TG_SESSION" in out
    assert tg == []
    assert counts["errors"] == 0


def test_a_dead_session_degrades_the_cycle_instead_of_failing_it(
    credentials, fake_preview, fake_telegram, capsys
):
    fake_preview(matched=4, unavailable_channels=("cyprusithr",))
    fake_telegram(effect=SystemExit("Telegram session is missing or expired."))

    counts = run(source="auto")

    assert counts["matched"] == 4
    assert counts["errors"] == 1
    assert "session is missing or expired" in capsys.readouterr().out


def test_an_mtproto_crash_degrades_the_cycle_instead_of_failing_it(
    credentials, fake_preview, fake_telegram, capsys
):
    fake_preview(matched=4, unavailable_channels=("cyprusithr",))
    fake_telegram(effect=ConnectionError("telegram unreachable"))

    counts = run(source="auto")

    assert counts["matched"] == 4
    assert counts["errors"] == 1
    assert "telegram unreachable" in capsys.readouterr().out


def test_the_window_and_full_flag_reach_the_backend(credentials, fake_preview):
    calls = fake_preview()

    run(source="preview", days=7, full=True)

    assert calls[0]["days"] == 7 and calls[0]["full"] is True


def test_telegram_configured_needs_all_three_variables(monkeypatch):
    for name, value in CREDENTIALS.items():
        monkeypatch.setenv(name, value)
    assert runner.telegram_configured()

    monkeypatch.setenv("TG_SESSION", "   ")
    assert not runner.telegram_configured()


def test_counts_start_from_the_shared_shape():
    assert set(ingest.new_counts()) == set(ingest.COUNTER_KEYS)
    assert all(v == 0 for v in ingest.new_counts().values())
