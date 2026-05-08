from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from hive_mp_cli.storage import db as db_store
from hive_mp_cli.storage import files as files_store


def _row(
    url: str,
    biz_id: str = "biz1",
    title: str = "t",
    fetch_status: str = "success",
    has_content: int = 1,
    local_path: str = "",
) -> dict:
    return {
        "id": db_store.article_id_for_url(url),
        "biz_id": biz_id,
        "faker_id": biz_id,
        "url": url,
        "title": title,
        "author": "",
        "publish_time": int(time.time()),
        "fetched_at": int(time.time()),
        "local_path": local_path,
        "summary": "",
        "article_type": 0,
        "fetch_status": fetch_status,
        "has_content": has_content,
    }


def test_article_id_is_deterministic() -> None:
    a = db_store.article_id_for_url("https://x.com/a")
    b = db_store.article_id_for_url("https://x.com/a")
    c = db_store.article_id_for_url("https://x.com/b")
    assert a == b
    assert a != c


def test_upsert_and_dedup(tmp_home: Path) -> None:
    with db_store.connect() as conn:
        new1 = db_store.upsert_article(conn, _row("https://x.com/1"))
        new2 = db_store.upsert_article(conn, _row("https://x.com/1"))
    assert new1 is True
    assert new2 is False


def test_upsert_preserves_existing_local_path_on_metadata_refresh(tmp_home: Path) -> None:
    first = _row("https://x.com/1")
    first["local_path"] = "A/2026-01-01--title.md"
    first["fetch_status"] = "success"
    refresh = {**first, "local_path": "", "fetch_status": "metadata-only"}

    with db_store.connect() as conn:
        assert db_store.upsert_article(conn, first) is True
        assert db_store.upsert_article(conn, refresh) is False
        row = db_store.get_article(conn, first["id"])

    assert row is not None
    assert row["local_path"] == "A/2026-01-01--title.md"
    assert row["fetch_status"] == "success"


def test_list_articles_filters(tmp_home: Path) -> None:
    with db_store.connect() as conn:
        db_store.upsert_article(conn, _row("https://x.com/1", biz_id="A"))
        db_store.upsert_article(conn, _row("https://x.com/2", biz_id="B"))
        a_rows = db_store.list_articles(conn, biz_id="A")
        b_rows = db_store.list_articles(conn, biz_id="B")
        all_rows = db_store.list_articles(conn)
    assert len(a_rows) == 1
    assert len(b_rows) == 1
    assert len(all_rows) == 2


def test_search(tmp_home: Path) -> None:
    with db_store.connect() as conn:
        db_store.upsert_article(conn, _row("https://x.com/1", title="Python tutorial"))
        db_store.upsert_article(conn, _row("https://x.com/2", title="Ruby quickstart"))
        rows = db_store.search_articles(conn, "Python")
    assert len(rows) == 1
    assert "Python" in rows[0]["title"]


def test_migrate_old_schema_adds_has_content_and_attempts(tmp_home: Path) -> None:
    """A pre-existing DB without the new columns should be migrated transparently."""
    from hive_mp_cli.config import PATHS

    # Hand-build the old schema (no has_content, no fetch_attempts).
    db_path = PATHS.db_file
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(db_path)
    raw.executescript(
        """
        CREATE TABLE articles (
            id TEXT PRIMARY KEY,
            biz_id TEXT NOT NULL,
            faker_id TEXT,
            url TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            author TEXT,
            publish_time INTEGER,
            fetched_at INTEGER,
            local_path TEXT,
            summary TEXT,
            article_type INTEGER,
            fetch_status TEXT
        );
        INSERT INTO articles (id, biz_id, url, title, local_path, fetch_status)
        VALUES ('id-success', 'A', 'https://x.com/a', 'T', 'A/file.md', 'success'),
               ('id-pending', 'A', 'https://x.com/b', 'T', '', 'metadata-only');
        """
    )
    raw.commit()
    raw.close()

    # connect() should ALTER TABLE on demand.
    with db_store.connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(articles)").fetchall()}
        assert "has_content" in cols
        assert "fetch_attempts" in cols
        success = db_store.get_article_status(conn, "id-success")
        pending = db_store.get_article_status(conn, "id-pending")
    # Backfill: rows with a real local_path are treated as already-fetched.
    assert success is not None and success["has_content"] == 1
    assert pending is not None and pending["has_content"] == 0


def test_get_article_status_returns_none_when_absent(tmp_home: Path) -> None:
    with db_store.connect() as conn:
        assert db_store.get_article_status(conn, "nope") is None


def test_get_article_status_after_upsert(tmp_home: Path) -> None:
    with db_store.connect() as conn:
        db_store.upsert_article(
            conn,
            _row("https://x.com/1", fetch_status="success", has_content=1, local_path="A/x.md"),
        )
        status = db_store.get_article_status(conn, db_store.article_id_for_url("https://x.com/1"))
    assert status is not None
    assert status["has_content"] == 1
    assert status["fetch_status"] == "success"
    assert status["fetch_attempts"] == 1


def test_upsert_increments_fetch_attempts(tmp_home: Path) -> None:
    url = "https://x.com/1"
    with db_store.connect() as conn:
        db_store.upsert_article(conn, _row(url, fetch_status="blocked", has_content=0))
        db_store.upsert_article(conn, _row(url, fetch_status="blocked", has_content=0))
        db_store.upsert_article(conn, _row(url, fetch_status="blocked", has_content=0))
        status = db_store.get_article_status(conn, db_store.article_id_for_url(url))
    assert status is not None
    assert status["fetch_attempts"] == 3


def test_upsert_preserves_has_content_after_repair_then_idle(tmp_home: Path) -> None:
    """Once has_content=1, a later metadata refresh must not flip it back to 0."""
    url = "https://x.com/1"
    with db_store.connect() as conn:
        db_store.upsert_article(
            conn, _row(url, fetch_status="success", has_content=1, local_path="A/x.md")
        )
        db_store.upsert_article(
            conn, _row(url, fetch_status="metadata-only", has_content=0, local_path="")
        )
        status = db_store.get_article_status(conn, db_store.article_id_for_url(url))
    assert status is not None
    assert status["has_content"] == 1
    assert status["fetch_status"] == "success"  # terminal status not overwritten


def test_should_retry_matrix() -> None:
    assert db_store.should_retry(None) is True
    assert db_store.should_retry({"has_content": 1, "fetch_status": "success", "fetch_attempts": 1}) is False
    assert db_store.should_retry({"has_content": 0, "fetch_status": "deleted", "fetch_attempts": 1}) is False
    assert db_store.should_retry({"has_content": 0, "fetch_status": "blocked", "fetch_attempts": db_store.MAX_FETCH_ATTEMPTS}) is False
    assert db_store.should_retry({"has_content": 0, "fetch_status": "blocked", "fetch_attempts": 1}) is True
    assert db_store.should_retry({"has_content": 0, "fetch_status": "metadata-only", "fetch_attempts": 0}) is True


def test_list_repair_candidates_filters_terminal_and_capped(tmp_home: Path) -> None:
    with db_store.connect() as conn:
        # Already succeeded — never a candidate.
        db_store.upsert_article(
            conn, _row("https://x.com/ok", fetch_status="success", has_content=1, local_path="A/ok.md")
        )
        # Deleted — terminal.
        db_store.upsert_article(
            conn, _row("https://x.com/del", fetch_status="deleted", has_content=0)
        )
        # Capped: 3 attempts of blocked.
        for _ in range(3):
            db_store.upsert_article(
                conn, _row("https://x.com/cap", fetch_status="blocked", has_content=0)
            )
        # Live candidate: blocked once, can still retry.
        db_store.upsert_article(
            conn, _row("https://x.com/live", fetch_status="blocked", has_content=0)
        )

        cands = db_store.list_repair_candidates(conn, biz_id="biz1")
    urls = {c["url"] for c in cands}
    assert urls == {"https://x.com/live"}


def test_sync_log_round_trip(tmp_home: Path) -> None:
    with db_store.connect() as conn:
        sid = db_store.start_sync(conn, biz_id="biz1", faker_id="fk1")
        db_store.finish_sync(conn, sid, new_articles=5)
        row = conn.execute("SELECT * FROM sync_log WHERE id = ?", (sid,)).fetchone()
    assert row["new_articles"] == 5
    assert row["finished_at"] is not None


# ----------------------------------------------------------- file naming
def test_safe_dirname() -> None:
    assert files_store.safe_dirname("Bad/Name") == "Bad_Name"
    assert files_store.safe_dirname("") == "unknown"
    assert files_store.safe_dirname("正常名字") == "正常名字"


def test_slugify_title() -> None:
    assert files_store.slugify_title("Hello World") == "Hello-World"
    assert files_store.slugify_title("a/b\\c") == "abc"


def test_write_article_creates_file(tmp_home: Path) -> None:
    root = tmp_home / "articles"
    p = files_store.write_article(root, "号A", 1700000000, "Hi", "# Hi\n\nbody")
    assert p.exists()
    assert p.read_text(encoding="utf-8").startswith("# Hi")
    assert p.parent.name == "号A"


def test_write_article_avoids_overwrite(tmp_home: Path) -> None:
    root = tmp_home / "articles"
    p1 = files_store.write_article(root, "A", 1700000000, "Same", "first")
    p2 = files_store.write_article(root, "A", 1700000000, "Same", "second")
    assert p1 != p2
    assert p1.read_text() == "first"
    assert p2.read_text() == "second"
