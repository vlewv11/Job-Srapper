from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "vacancies.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vacancies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel     TEXT    NOT NULL,
    message_id  INTEGER NOT NULL,
    slot        INTEGER NOT NULL DEFAULT 0,
    posted_at   TEXT    NOT NULL,
    title       TEXT,
    company     TEXT,
    salary      TEXT,
    location    TEXT,
    remote      INTEGER NOT NULL DEFAULT 0,
    contact     TEXT,
    url         TEXT,
    raw_text    TEXT,
    scraped_at  TEXT    NOT NULL,
    UNIQUE (channel, message_id, slot)
);
CREATE INDEX IF NOT EXISTS idx_vacancies_posted_at ON vacancies (posted_at);
CREATE INDEX IF NOT EXISTS idx_vacancies_channel   ON vacancies (channel);
"""

_COLUMNS = {"contact": "TEXT", "slot": "INTEGER NOT NULL DEFAULT 0"}


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(vacancies)")}
    for name, decl in _COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE vacancies ADD COLUMN {name} {decl}")


@contextmanager
def connect(path: Path | str = DB_PATH):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def delete_message(conn: sqlite3.Connection, channel: str, message_id: int) -> None:
    """Remove all vacancy rows from one message (before re-inserting its slots)."""
    conn.execute(
        "DELETE FROM vacancies WHERE channel = ? AND message_id = ?",
        (channel, message_id),
    )


def insert(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT INTO vacancies
            (channel, message_id, slot, posted_at, title, company, salary,
             location, remote, contact, url, raw_text, scraped_at)
        VALUES
            (:channel, :message_id, :slot, :posted_at, :title, :company, :salary,
             :location, :remote, :contact, :url, :raw_text, :scraped_at)
        """,
        row,
    )


def query(
    conn: sqlite3.Connection,
    days: int | None = None,
    channel: str | None = None,
    search: str | None = None,
    remote_only: bool = False,
    limit: int = 1000,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM vacancies WHERE 1=1"
    params: list = []
    if days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        sql += " AND posted_at >= ?"
        params.append(cutoff)
    if channel:
        sql += " AND channel = ?"
        params.append(channel)
    if remote_only:
        sql += " AND remote = 1"
    if search:
        sql += " AND (title LIKE ? OR company LIKE ? OR raw_text LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    sql += " ORDER BY posted_at DESC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def channels(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT channel FROM vacancies ORDER BY channel"
    ).fetchall()
    return [r["channel"] for r in rows]


def stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
    last = conn.execute("SELECT MAX(scraped_at) FROM vacancies").fetchone()[0]
    return {"total": total, "last_scraped": last}
