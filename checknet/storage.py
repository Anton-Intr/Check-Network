from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_DB_PATH = Path("checknet.sqlite3")


SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at TEXT NOT NULL,
    target TEXT NOT NULL,
    ok INTEGER NOT NULL,
    status_code INTEGER,
    latency_ms REAL,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_requests_checked_at ON requests (checked_at);
CREATE INDEX IF NOT EXISTS idx_requests_target_checked_at ON requests (target, checked_at);
"""


@contextmanager
def connect(db_path: str | Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    path = Path(db_path)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def insert_request(
    conn: sqlite3.Connection,
    *,
    checked_at: str,
    target: str,
    ok: bool,
    status_code: int | None,
    latency_ms: float | None,
    error: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO requests (checked_at, target, ok, status_code, latency_ms, error)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (checked_at, target, int(ok), status_code, latency_ms, error),
    )
