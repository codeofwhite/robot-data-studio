from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import BACKEND_ROOT, settings


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def transaction(db_path: Path | None = None):
    connection = connect(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(db_path: Path | None = None) -> None:
    migration = (BACKEND_ROOT / "migrations" / "001_initial.sql").read_text(encoding="utf-8")
    with transaction(db_path) as connection:
        connection.executescript(migration)
