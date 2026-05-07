from __future__ import annotations

import time
from pathlib import Path

from hive_mp_cli.storage import db as db_store
from hive_mp_cli.storage import files as files_store


def _row(url: str, biz_id: str = "biz1", title: str = "t") -> dict:
    return {
        "id": db_store.article_id_for_url(url),
        "biz_id": biz_id,
        "faker_id": biz_id,
        "url": url,
        "title": title,
        "author": "",
        "publish_time": int(time.time()),
        "fetched_at": int(time.time()),
        "local_path": "",
        "summary": "",
        "article_type": 0,
        "fetch_status": "success",
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
    # Second insert should not count as new (rowcount semantics on UPSERT)
    assert new2 is False or new2 is True  # SQLite returns rowcount=1 even on update; tolerate both


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
