from __future__ import annotations

import pytest
from conftest import add_row
from fastapi.testclient import TestClient

from src.web.app import app


@pytest.fixture
def client(db_path, monkeypatch):
    monkeypatch.delenv("AUTO_SCRAPE", raising=False)
    with TestClient(app) as c:
        yield c


def test_index_serves_the_dashboard(client, conn):
    add_row(conn, message_id=1, title="LLM Researcher", company="Acme")
    conn.commit()

    r = client.get("/")
    assert r.status_code == 200
    assert "LLM Researcher" in r.text
    assert "Remote only" not in r.text


def test_index_offers_only_the_three_time_filters(client):
    body = client.get("/").text
    for key in ("today", "7d", "30d"):
        assert f'value="{key}"' in body
    assert 'value="60d"' not in body and 'value="90d"' not in body


def test_healthz_reports_state(client, conn):
    add_row(conn, message_id=1)
    conn.commit()

    payload = client.get("/healthz").json()
    assert payload["status"] == "ok"
    assert payload["vacancies"] == 1
    assert payload["retention_days"] == 30
    assert payload["interval_minutes"] == 10
    assert payload["auto_scrape"] is False


def test_dashboard_has_no_query_filters_left(client):
    plain = client.get("/").text
    assert client.get("/?days=7&remote=1").text.count("<tr data-ts=") == plain.count("<tr data-ts=")
