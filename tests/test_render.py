from __future__ import annotations

import re

from conftest import add_row

from src import config
from src.web import render


def test_ranges_are_exactly_today_7d_30d():
    assert [r["key"] for r in render.RANGES] == ["today", "7d", "30d"]
    assert [r["label"] for r in render.RANGES] == ["Today", "7 days", "30 days"]


def test_context_only_carries_the_retention_window(conn, monkeypatch):
    monkeypatch.setattr(config, "RETENTION_DAYS", 30)
    add_row(conn, message_id=1, age_days=1, title="fresh")
    add_row(conn, message_id=2, age_days=45, title="stale")

    ctx = render.build_context(conn)
    assert [v["title"] for v in ctx["vacancies"]] == ["fresh"]
    assert ctx["count"] == 1


def test_row_view_exposes_client_side_filter_data(conn):
    add_row(conn, message_id=1, title="LLM Engineer", company="Acme",
            raw_text="Мы ищем LLM инженера, стек PyTorch")
    ctx = render.build_context(conn)
    row = ctx["vacancies"][0]

    assert row["posted_ts"] > 0
    assert "pytorch" in row["search"]
    assert "llm engineer" in row["search"]
    assert row["search"] == row["search"].lower()


def test_missing_fields_fall_back(conn):
    add_row(conn, message_id=1, title=None, company=None, salary=None,
            location=None, contact=None, channel="somechan")
    row = render.build_context(conn)["vacancies"][0]
    assert row["title"] == "Untitled role"
    assert row["company"] == "somechan"
    assert row["salary"] == "—" and row["location"] == "—" and row["contact"] == "—"
    assert row["contact_href"] is None


def test_contact_href():
    assert render.contact_href("@hr_bob") == "https://t.me/hr_bob"
    assert render.contact_href("jobs@acme.io") == "mailto:jobs@acme.io"
    assert render.contact_href("https://acme.io/jobs") == "https://acme.io/jobs"
    assert render.contact_href("Anna HR") is None
    assert render.contact_href(None) is None


def test_rendered_page_has_the_three_filters_and_no_remote_only(conn):
    add_row(conn, message_id=1, title="ML Engineer", remote=1)
    html = render.render_index(conn)

    assert 'value="today"' in html and 'value="7d"' in html and 'value="30d"' in html
    assert "Remote only" not in html
    assert 'name="remote"' not in html
    assert "60d" not in html and "90d" not in html
    assert re.search(r'<tr data-ts="\d+" data-channel="ch" data-search="', html)


def test_remote_badge_survives_as_a_label(conn):
    add_row(conn, message_id=1, remote=1)
    assert '<span class="pill">remote</span>' in render.render_index(conn)


def test_empty_db_renders_a_placeholder(conn):
    html = render.render_index(conn)
    assert "Nothing scraped yet" in html


def test_html_is_escaped(conn):
    add_row(conn, message_id=1, title='<script>alert("x")</script>')
    html = render.render_index(conn)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
