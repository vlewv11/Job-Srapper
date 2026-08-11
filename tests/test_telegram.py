from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src import db
from src.scraping import patterns, telegram

VACANCY = "Senior ML Engineer, remote, отклик @hr_bob"
NOISE = "Всем привет, как дела?"


class FakeMessage:
    def __init__(self, mid: int, age_days: float, text: str):
        self.id = mid
        self.date = datetime.now(timezone.utc) - timedelta(days=age_days)
        self.message = text
        self.post_author = None
        self.reply_to = None

    async def get_sender(self):
        return None


class FakeEntity:
    username = "somechan"
    forum = False
    id = 4242


class FakeClient:
    def __init__(self, messages):
        self.messages = messages
        self.requests: list[dict] = []
        self.disconnected = False

    async def get_entity(self, channel):
        return FakeEntity()

    def iter_messages(self, entity, limit=None, min_id=0):
        self.requests.append({"limit": limit, "min_id": min_id})
        selected = sorted(
            (m for m in self.messages if m.id > min_id),
            key=lambda m: m.id,
            reverse=True,
        )[: limit or None]

        async def gen():
            for m in selected:
                yield m

        return gen()

    async def disconnect(self):
        self.disconnected = True


@pytest.fixture
def fake_telegram(monkeypatch):
    def install(messages):
        client = FakeClient(messages)

        async def _connected():
            return client

        monkeypatch.setattr(telegram, "connected_client", _connected)
        return client

    return install


def run_scrape(**kwargs):
    return asyncio.run(telegram.scrape(channels=["somechan"], verbose=False, **kwargs))


def test_load_channels_normalizes_every_form(tmp_path):
    f = tmp_path / "channels.txt"
    f.write_text(
        "# comment\n\nhttps://t.me/alpha\nt.me/beta\n@gamma\n  delta  \n",
        encoding="utf-8",
    )
    assert telegram.load_channels(f) == ["alpha", "beta", "gamma", "delta"]


def test_load_channels_missing_file(tmp_path):
    assert telegram.load_channels(tmp_path / "nope.txt") == []


def test_message_url_public_and_private():
    assert telegram._message_url("c", FakeEntity(), 12) == "https://t.me/somechan/12"

    class Private:
        username = None
        id = 99

    assert telegram._message_url("c", Private(), 12) == "https://t.me/c/99/12"


def test_store_message_replaces_previous_slots(conn):
    vacs = patterns.parse_all("1) ML Engineer в Acme, отклик @a\n2) Data Scientist в Globex, remote, отклик @b")
    assert len(vacs) == 2

    telegram.store_message(
        conn, channel="c", message_id=5, posted_at="2026-08-01T00:00:00+00:00",
        url="u", text="t", vacancies=vacs,
    )
    assert len(db.query(conn, days=None)) == 2

    telegram.store_message(
        conn, channel="c", message_id=5, posted_at="2026-08-01T00:00:00+00:00",
        url="u", text="t", vacancies=vacs[:1],
    )
    assert len(db.query(conn, days=None)) == 1


def test_store_message_falls_back_to_the_author_contact(conn):
    vacs = patterns.parse_all("Senior ML Engineer, Москва, офис")
    assert vacs and vacs[0].contact is None

    telegram.store_message(
        conn, channel="c", message_id=1, posted_at="2026-08-01T00:00:00+00:00",
        url="u", text="t", vacancies=vacs, fallback_contact="@channel_owner",
    )
    assert db.query(conn, days=None)[0]["contact"] == "@channel_owner"


def test_first_scrape_reads_the_whole_window_then_goes_incremental(db_path, fake_telegram):
    client = fake_telegram([
        FakeMessage(10, 1.0, VACANCY),
        FakeMessage(11, 0.5, NOISE),
        FakeMessage(12, 0.1, VACANCY),
    ])

    counts = run_scrape()
    assert counts["matched"] == 2
    assert client.requests[0]["min_id"] == 0

    with db.connect() as conn:
        assert db.get_watermark(conn, "somechan") == 12
        assert len(db.query(conn)) == 2

    client.messages.append(FakeMessage(13, 0.01, VACANCY))
    counts = run_scrape()
    assert client.requests[-1]["min_id"] == 12
    assert counts["scanned"] == 1
    assert counts["matched"] == 1

    with db.connect() as conn:
        assert db.get_watermark(conn, "somechan") == 13
        assert len(db.query(conn)) == 3


def test_posts_older_than_the_window_are_never_downloaded(db_path, fake_telegram):
    client = fake_telegram([
        FakeMessage(1, 90, VACANCY),
        FakeMessage(2, 45, VACANCY),
        FakeMessage(3, 2, VACANCY),
    ])
    counts = run_scrape(days=30)

    assert counts["matched"] == 1
    with db.connect() as conn:
        assert len(db.query(conn, days=None)) == 1


def test_dormant_channel_is_not_re_read_every_cycle(db_path, fake_telegram):
    client = fake_telegram([FakeMessage(5, 60, VACANCY), FakeMessage(6, 55, VACANCY)])

    run_scrape(days=30)
    with db.connect() as conn:
        assert db.get_watermark(conn, "somechan") == 6

    run_scrape(days=30)
    assert client.requests[-1]["min_id"] == 6


def test_cycle_prunes_expired_rows(db_path, fake_telegram):
    with db.connect() as conn:
        from conftest import add_row
        add_row(conn, channel="somechan", message_id=999, age_days=40, title="expired")

    fake_telegram([FakeMessage(1, 1, VACANCY)])
    counts = run_scrape(days=30)

    assert counts["pruned"] == 1
    with db.connect() as conn:
        rows = db.query(conn, days=None)
        assert len(rows) == 1
        assert rows[0]["title"].startswith("Senior ML Engineer")


def test_full_scrape_ignores_the_watermark(db_path, fake_telegram):
    client = fake_telegram([FakeMessage(10, 1, VACANCY)])
    run_scrape()
    assert client.requests[-1]["min_id"] == 0

    run_scrape()
    assert client.requests[-1]["min_id"] == 10

    run_scrape(full=True)
    assert client.requests[-1]["min_id"] == 0


def test_watermark_advances_even_when_nothing_matches(db_path, fake_telegram):
    fake_telegram([FakeMessage(7, 1, NOISE)])
    counts = run_scrape()

    assert counts["matched"] == 0
    with db.connect() as conn:
        assert db.get_watermark(conn, "somechan") == 7
        assert db.stats(conn)["last_scraped"] is not None


def test_promo_posts_are_counted_and_skipped(db_path, fake_telegram):
    fake_telegram([FakeMessage(1, 1, "Открытый урок для ML инженеров, erid=2Vfn")])
    counts = run_scrape()
    assert counts["promo_skipped"] == 1
    assert counts["matched"] == 0


def test_client_is_disconnected_after_a_cycle(db_path, fake_telegram):
    client = fake_telegram([FakeMessage(1, 1, VACANCY)])
    run_scrape()
    assert client.disconnected
