from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def _positive_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _path(name: str, default: Path) -> Path:
    raw = (os.getenv(name) or "").strip()
    return Path(raw).expanduser() if raw else default


def _choice(name: str, allowed: tuple[str, ...], default: str) -> str:
    raw = (os.getenv(name) or "").strip().lower()
    return raw if raw in allowed else default


RETENTION_DAYS = _positive_int("RETENTION_DAYS", 30)

SCRAPE_SOURCE = _choice("SCRAPE_SOURCE", ("auto", "preview", "telegram"), "auto")

SCRAPE_INTERVAL_MINUTES = _positive_int("SCRAPE_INTERVAL_MINUTES", 10)

DATA_DIR = _path("DATA_DIR", ROOT / "data")
DB_PATH = _path("DB_PATH", DATA_DIR / "vacancies.db")
SITE_DIR = _path("SITE_DIR", ROOT / "site")
CHANNELS_FILE = _path("CHANNELS_FILE", ROOT / "channels.txt")
SESSION_PATH = str(_path("SESSION_PATH", DATA_DIR / "job_scraper.session"))
