from __future__ import annotations

import json

from conftest import add_row

from src.web.build import build_site


def test_build_site_writes_a_self_contained_page(conn, tmp_path):
    add_row(conn, message_id=1, title="ML Engineer", company="Acme")
    conn.commit()

    out = build_site(tmp_path / "site")
    html = (out / "index.html").read_text(encoding="utf-8")

    assert (out / ".nojekyll").exists()
    assert "ML Engineer" in html
    assert "Acme" in html
    assert 'value="today"' in html and 'value="30d"' in html
    assert "<script>" in html


def test_build_site_also_exports_json(conn, tmp_path):
    add_row(conn, message_id=1, title="ML Engineer")
    conn.commit()

    out = build_site(tmp_path / "site")
    data = json.loads((out / "vacancies.json").read_text(encoding="utf-8"))

    assert data["count"] == 1
    assert data["retention_days"] >= 1
    assert data["vacancies"][0]["title"] == "ML Engineer"
    assert "search" not in data["vacancies"][0]
