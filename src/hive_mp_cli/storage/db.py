"""SQLite store for articles + sync_log. WAL mode for safety."""
from __future__ import annotations

import contextlib
import hashlib
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from hive_mp_cli.config import PATHS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id            TEXT PRIMARY KEY,
    biz_id        TEXT NOT NULL,
    faker_id      TEXT,
    url           TEXT UNIQUE NOT NULL,
    title         TEXT NOT NULL,
    author        TEXT,
    publish_time  INTEGER,
    fetched_at    INTEGER,
    local_path    TEXT,
    summary       TEXT,
    article_type  INTEGER,
    fetch_status  TEXT
);

CREATE INDEX IF NOT EXISTS idx_articles_biz ON articles(biz_id, publish_time DESC);
CREATE INDEX IF NOT EXISTS idx_articles_faker ON articles(faker_id, publish_time DESC);

CREATE TABLE IF NOT EXISTS sync_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    biz_id        TEXT,
    faker_id      TEXT,
    started_at    INTEGER,
    finished_at   INTEGER,
    new_articles  INTEGER,
    error         TEXT
);
"""


def article_id_for_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


@contextlib.contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    PATHS.home.mkdir(parents=True, exist_ok=True)
    path = db_path or PATHS.db_file
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_article(conn: sqlite3.Connection, row: dict[str, Any]) -> bool:
    """Insert if new. Returns True if new row was inserted."""
    cur = conn.execute(
        """
        INSERT INTO articles (id, biz_id, faker_id, url, title, author, publish_time,
                               fetched_at, local_path, summary, article_type, fetch_status)
        VALUES (:id, :biz_id, :faker_id, :url, :title, :author, :publish_time,
                :fetched_at, :local_path, :summary, :article_type, :fetch_status)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title,
            author=excluded.author,
            publish_time=excluded.publish_time,
            local_path=excluded.local_path,
            summary=excluded.summary,
            article_type=excluded.article_type,
            fetch_status=excluded.fetch_status
        """,
        row,
    )
    return cur.rowcount > 0 and cur.lastrowid is not None


def has_article(conn: sqlite3.Connection, article_id: str) -> bool:
    return conn.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,)).fetchone() is not None


def list_articles(
    conn: sqlite3.Connection,
    biz_id: str | None = None,
    faker_id: str | None = None,
    since: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM articles WHERE 1=1"
    params: list[Any] = []
    if biz_id:
        sql += " AND biz_id = ?"
        params.append(biz_id)
    if faker_id:
        sql += " AND faker_id = ?"
        params.append(faker_id)
    if since:
        sql += " AND publish_time >= ?"
        params.append(since)
    sql += " ORDER BY publish_time DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_article(conn: sqlite3.Connection, article_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM articles WHERE id = ? OR url = ?", (article_id, article_id)).fetchone()
    return dict(row) if row else None


def search_articles(conn: sqlite3.Connection, keyword: str, limit: int = 50) -> list[dict[str, Any]]:
    pattern = f"%{keyword}%"
    rows = conn.execute(
        "SELECT * FROM articles WHERE title LIKE ? OR summary LIKE ? "
        "ORDER BY publish_time DESC LIMIT ?",
        (pattern, pattern, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def start_sync(conn: sqlite3.Connection, biz_id: str | None, faker_id: str | None) -> int:
    cur = conn.execute(
        "INSERT INTO sync_log (biz_id, faker_id, started_at) VALUES (?, ?, ?)",
        (biz_id, faker_id, int(time.time())),
    )
    conn.commit()
    return cur.lastrowid or 0


def finish_sync(
    conn: sqlite3.Connection, sync_id: int, new_articles: int, error: str | None = None
) -> None:
    conn.execute(
        "UPDATE sync_log SET finished_at = ?, new_articles = ?, error = ? WHERE id = ?",
        (int(time.time()), new_articles, error, sync_id),
    )
    conn.commit()
