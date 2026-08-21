from __future__ import annotations

import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from src import config, db


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError(
            "a test tried to open a network connection; pass a fake fetch/client in"
        )

    monkeypatch.setattr(urllib.request, "urlopen", blocked)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "vacancies.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    return path


@pytest.fixture
def conn(db_path):
    with db.connect() as connection:
        yield connection


def days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def add_row(conn, *, channel="ch", message_id=1, slot=0, age_days=1.0, title="ML Engineer",
            company=None, salary=None, location=None, remote=0, contact=None,
            url=None, raw_text="ML Engineer needed"):
    db.insert(conn, {
        "channel": channel,
        "message_id": message_id,
        "slot": slot,
        "posted_at": days_ago(age_days),
        "title": title,
        "company": company,
        "salary": salary,
        "location": location,
        "remote": remote,
        "contact": contact,
        "url": url or f"https://t.me/{channel}/{message_id}",
        "raw_text": raw_text,
        "scraped_at": days_ago(0),
    })
