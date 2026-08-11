from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

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

CREATE TABLE IF NOT EXISTS channel_state (
    channel         TEXT    PRIMARY KEY,
    last_message_id INTEGER NOT NULL DEFAULT 0,
    last_posted_at  TEXT,
    last_run_at     TEXT
);
"""

_COLUMNS = {"contact": "TEXT", "slot": "INTEGER NOT NULL DEFAULT 0"}


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(vacancies)")}
    for name, decl in _COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE vacancies ADD COLUMN {name} {decl}")


@contextmanager
def connect(path: Path | str | None = None):
    path = Path(path) if path else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
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
    since: datetime | None = None,
    channel: str | None = None,
    search: str | None = None,
    limit: int = 5000,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM vacancies WHERE 1=1"
    params: list = []
    if since is None and days:
        since = datetime.now(timezone.utc) - timedelta(days=days)
    if since is not None:
        sql += " AND posted_at >= ?"
        params.append(since.isoformat())
    if channel:
        sql += " AND channel = ?"
        params.append(channel)
    if search:
        sql += " AND (title LIKE ? OR company LIKE ? OR raw_text LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    sql += " ORDER BY posted_at DESC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def prune(conn: sqlite3.Connection, days: int | None = None) -> int:
    days = config.RETENTION_DAYS if days is None else days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cur = conn.execute("DELETE FROM vacancies WHERE posted_at < ?", (cutoff,))
    return cur.rowcount or 0


def get_watermark(conn: sqlite3.Connection, channel: str) -> int:
    row = conn.execute(
        "SELECT last_message_id FROM channel_state WHERE channel = ?", (channel,)
    ).fetchone()
    return int(row["last_message_id"]) if row else 0


def set_watermark(
    conn: sqlite3.Connection,
    channel: str,
    message_id: int,
    posted_at: str | None,
    run_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO channel_state (channel, last_message_id, last_posted_at, last_run_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(channel) DO UPDATE SET
            last_message_id = MAX(excluded.last_message_id, channel_state.last_message_id),
            last_posted_at  = COALESCE(excluded.last_posted_at, channel_state.last_posted_at),
            last_run_at     = excluded.last_run_at
        """,
        (channel, message_id, posted_at, run_at),
    )


def channels(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT channel FROM vacancies ORDER BY channel"
    ).fetchall()
    return [r["channel"] for r in rows]


def stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
    oldest = conn.execute("SELECT MIN(posted_at) FROM vacancies").fetchone()[0]
    scraped = conn.execute("SELECT MAX(scraped_at) FROM vacancies").fetchone()[0]
    ran = conn.execute("SELECT MAX(last_run_at) FROM channel_state").fetchone()[0]
    last = max([v for v in (scraped, ran) if v], default=None)
    return {"total": total, "last_scraped": last, "oldest": oldest}
