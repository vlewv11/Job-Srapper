from __future__ import annotations

import json
from pathlib import Path

from .. import config, db
from . import render


def build_site(out_dir: Path | str | None = None) -> Path:
    out = Path(out_dir) if out_dir else config.SITE_DIR
    out.mkdir(parents=True, exist_ok=True)

    with db.connect() as conn:
        context = render.build_context(conn)
        html = render.render_html(context)

    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    (out / "vacancies.json").write_text(
        json.dumps(
            {
                "generated_at": context["generated_at"],
                "retention_days": context["retention_days"],
                "count": context["count"],
                "vacancies": [
                    {k: v for k, v in row.items() if k != "search"}
                    for row in context["vacancies"]
                ],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return out
