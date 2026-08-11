from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import add_row, days_ago

from src import config, db


def test_insert_and_query_window(conn):
    add_row(conn, message_id=1, age_days=0.2, title="Today role")
    add_row(conn, message_id=2, age_days=3, title="This week")
    add_row(conn, message_id=3, age_days=20, title="This month")

    assert len(db.query(conn, days=1)) == 1
    assert len(db.query(conn, days=7)) == 2
    assert len(db.query(conn, days=30)) == 3


def test_query_since_beats_days(conn):
    add_row(conn, message_id=1, age_days=0.1)
    add_row(conn, message_id=2, age_days=5)
    since = datetime.now(timezone.utc) - timedelta(days=1)
    assert len(db.query(conn, days=30, since=since)) == 1


def test_query_orders_newest_first(conn):
    add_row(conn, message_id=1, age_days=9, title="older")
    add_row(conn, message_id=2, age_days=1, title="newer")
    assert [r["title"] for r in db.query(conn)] == ["newer", "older"]


def test_query_channel_and_search(conn):
    add_row(conn, channel="a", message_id=1, title="LLM Engineer", raw_text="remote llm role")
    add_row(conn, channel="b", message_id=2, title="Data Scientist", raw_text="onsite ds role")

    assert len(db.query(conn, channel="a")) == 1
    assert len(db.query(conn, search="Data Scientist")) == 1
    assert len(db.query(conn, search="onsite")) == 1
    assert len(db.query(conn, channel="a", search="Data Scientist")) == 0


def test_delete_message_clears_every_slot(conn):
    add_row(conn, message_id=7, slot=0, title="first")
    add_row(conn, message_id=7, slot=1, title="second")
    assert len(db.query(conn)) == 2

    db.delete_message(conn, "ch", 7)
    add_row(conn, message_id=7, slot=0, title="only one now")
    assert [r["title"] for r in db.query(conn)] == ["only one now"]


def test_prune_drops_expired_rows(conn):
    add_row(conn, message_id=1, age_days=2, title="keep")
    add_row(conn, message_id=2, age_days=31, title="drop")
    add_row(conn, message_id=3, age_days=400, title="drop too")

    assert db.prune(conn, 30) == 2
    assert [r["title"] for r in db.query(conn, days=None)] == ["keep"]


def test_prune_defaults_to_configured_retention(conn, monkeypatch):
    monkeypatch.setattr(config, "RETENTION_DAYS", 7)
    add_row(conn, message_id=1, age_days=3)
    add_row(conn, message_id=2, age_days=10)
    assert db.prune(conn) == 1


def test_watermark_roundtrip_and_monotonic(conn):
    assert db.get_watermark(conn, "ch") == 0

    db.set_watermark(conn, "ch", 100, days_ago(1), days_ago(0))
    assert db.get_watermark(conn, "ch") == 100

    db.set_watermark(conn, "ch", 50, days_ago(2), days_ago(0))
    assert db.get_watermark(conn, "ch") == 100

    db.set_watermark(conn, "ch", 140, days_ago(0), days_ago(0))
    assert db.get_watermark(conn, "ch") == 140


def test_stats_uses_run_time_even_without_rows(conn):
    ran = days_ago(0)
    db.set_watermark(conn, "ch", 5, None, ran)
    meta = db.stats(conn)
    assert meta["total"] == 0
    assert meta["last_scraped"] == ran


def test_channels_are_distinct_and_sorted(conn):
    add_row(conn, channel="b", message_id=1)
    add_row(conn, channel="a", message_id=2)
    add_row(conn, channel="a", message_id=3)
    assert db.channels(conn) == ["a", "b"]


def test_query_has_no_remote_filter():
    import inspect

    assert "remote" not in inspect.signature(db.query).parameters
