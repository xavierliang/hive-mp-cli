"""SQLite store for articles + sync_log. WAL mode for safety.

Schema evolution: ``has_content`` and ``fetch_attempts`` columns power incremental
repair of articles whose body fetch failed. Old DBs are migrated transparently
on connect via ``PRAGMA table_info`` + ``ALTER TABLE``.
"""
from __future__ import annotations

import contextlib
import hashlib
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from hive_mp_cli.config import PATHS

MAX_FETCH_ATTEMPTS = 3
"""Per-article retry cap. Past this we treat the URL as dead."""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id              TEXT PRIMARY KEY,
    biz_id          TEXT NOT NULL,
    faker_id        TEXT,
    url             TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    author          TEXT,
    publish_time    INTEGER,
    fetched_at      INTEGER,
    local_path      TEXT,
    summary         TEXT,
    article_type    INTEGER,
    fetch_status    TEXT,
    has_content     INTEGER NOT NULL DEFAULT 0,
    fetch_attempts  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_articles_biz ON articles(biz_id, publish_time DESC);
CREATE INDEX IF NOT EXISTS idx_articles_faker ON articles(faker_id, publish_time DESC);
-- idx_articles_pending references columns added by _migrate(); created there.

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


_CANONICAL_QUERY_KEYS = frozenset({"__biz", "mid", "idx", "sn"})


def _canonical_url_key(url: str) -> str:
    """Strip tracking/session params so equivalent URLs share a key.

    WeChat article URLs come in two shapes:
      - ``/s/<token>?chksm=...&scene=...`` (modern): token alone identifies it
      - ``/s?__biz=...&mid=...&idx=...&sn=...&chksm=...`` (legacy): the first
        four params identify it; the rest are tracking
    Anything else is returned unchanged.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.path.startswith("/s/"):
        return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"
    if parts.path == "/s" and parts.query:
        params = sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=False)
            if k in _CANONICAL_QUERY_KEYS
        )
        if params:
            return f"{parts.scheme}://{parts.netloc}/s?" + urlencode(params)
    return url


def article_id_for_url(url: str) -> str:
    return hashlib.sha256(_canonical_url_key(url).encode("utf-8")).hexdigest()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add has_content / fetch_attempts to old DBs that pre-date the repair feature."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(articles)").fetchall()}
    if "has_content" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN has_content INTEGER NOT NULL DEFAULT 0")
        # Backfill: any row with a real local_path is a successful fetch.
        conn.execute(
            "UPDATE articles SET has_content = 1 "
            "WHERE local_path IS NOT NULL AND local_path != ''"
        )
    if "fetch_attempts" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN fetch_attempts INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE articles SET fetch_attempts = 1")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_pending ON articles(has_content, fetch_attempts)"
    )


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
        _migrate(conn)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def upsert_article(conn: sqlite3.Connection, row: dict[str, Any]) -> bool:
    """Insert if new. Returns True if a new row was inserted.

    On conflict the merge is conservative: terminal states (success/deleted,
    populated local_path, has_content=1) are preserved so a metadata-only
    refresh can never wipe a successful prior fetch. ``fetch_attempts`` always
    increments by 1 — every call counts as a try.
    """
    payload = dict(row)
    payload.setdefault("has_content", 0)
    existed = has_article(conn, payload["id"])
    conn.execute(
        """
        INSERT INTO articles (id, biz_id, faker_id, url, title, author, publish_time,
                              fetched_at, local_path, summary, article_type, fetch_status,
                              has_content, fetch_attempts)
        VALUES (:id, :biz_id, :faker_id, :url, :title, :author, :publish_time,
                :fetched_at, :local_path, :summary, :article_type, :fetch_status,
                :has_content, 1)
        ON CONFLICT(id) DO UPDATE SET
            title=COALESCE(NULLIF(excluded.title, ''), title),
            author=COALESCE(NULLIF(excluded.author, ''), author),
            publish_time=COALESCE(excluded.publish_time, publish_time),
            fetched_at=excluded.fetched_at,
            local_path=COALESCE(NULLIF(excluded.local_path, ''), local_path),
            summary=COALESCE(NULLIF(excluded.summary, ''), summary),
            article_type=excluded.article_type,
            fetch_status=CASE
                WHEN articles.fetch_status IN ('success', 'deleted')
                    THEN articles.fetch_status
                WHEN excluded.fetch_status = 'metadata-only'
                     AND excluded.local_path = ''
                     AND COALESCE(articles.local_path, '') <> ''
                THEN articles.fetch_status
                ELSE COALESCE(NULLIF(excluded.fetch_status, ''), articles.fetch_status)
            END,
            has_content=CASE
                WHEN articles.has_content = 1 OR excluded.has_content = 1 THEN 1
                ELSE 0
            END,
            fetch_attempts=articles.fetch_attempts + 1
        """,
        payload,
    )
    return not existed


def has_article(conn: sqlite3.Connection, article_id: str) -> bool:
    return conn.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,)).fetchone() is not None


def get_article_status(conn: sqlite3.Connection, article_id: str) -> dict[str, Any] | None:
    """Return enough state to decide whether to skip / retry this article. None if absent."""
    row = conn.execute(
        "SELECT has_content, fetch_status, fetch_attempts, local_path "
        "FROM articles WHERE id = ?",
        (article_id,),
    ).fetchone()
    return dict(row) if row else None


def should_retry(status: dict[str, Any] | None) -> bool:
    """Decide whether an existing article warrants a body refetch.

    None              → True  (caller should treat as new)
    has_content=1     → False (already succeeded)
    fetch_status=deleted → False (terminal)
    fetch_attempts >= MAX_FETCH_ATTEMPTS → False (gave up)
    otherwise         → True
    """
    if status is None:
        return True
    if int(status.get("has_content") or 0) == 1:
        return False
    if status.get("fetch_status") == "deleted":
        return False
    if int(status.get("fetch_attempts") or 0) >= MAX_FETCH_ATTEMPTS:
        return False
    return True


def list_repair_candidates(
    conn: sqlite3.Connection,
    biz_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Articles whose body is missing but still worth retrying.

    Excludes terminal ``deleted`` and rows that already hit ``MAX_FETCH_ATTEMPTS``.
    """
    sql = (
        "SELECT * FROM articles "
        "WHERE has_content = 0 "
        "AND COALESCE(fetch_status, '') != 'deleted' "
        "AND fetch_attempts < ?"
    )
    params: list[Any] = [MAX_FETCH_ATTEMPTS]
    if biz_id:
        sql += " AND biz_id = ?"
        params.append(biz_id)
    sql += " ORDER BY publish_time DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


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
    row = conn.execute(
        "SELECT * FROM articles WHERE id = ? OR url = ?", (article_id, article_id)
    ).fetchone()
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
