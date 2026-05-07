from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from hive_mp_cli.cli import app
from hive_mp_cli.commands import article as article_cmd
from hive_mp_cli.commands import sync as sync_cmd
from hive_mp_cli.storage import db as db_store
from hive_mp_cli.wechat.gather.base import GatherConfig


def _item(url: str = "https://mp.weixin.qq.com/s/abc") -> dict[str, Any]:
    return {
        "link": url,
        "title": "Test title",
        "update_time": 1_700_000_000,
        "digest": "list digest",
    }


def _patch_one_item(monkeypatch: Any, item: dict[str, Any] | None = None) -> None:
    monkeypatch.setattr(sync_cmd, "random_sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sync_cmd,
        "_iter_list",
        lambda api, faker_id, cfg, mode: iter([item or _item()]),
    )


def test_sync_preserves_blocked_status_without_markdown(
    tmp_home: Path,
    monkeypatch: Any,
) -> None:
    class BlockedFetcher:
        async def start(self) -> None:
            pass

        async def close(self) -> None:
            pass

        async def fetch(self, url: str) -> dict[str, Any]:
            return {
                "content": "",
                "fetch_status": "blocked",
                "article_type": 0,
                "author": "",
                "mp_info": {"mp_name": "Account A"},
            }

    _patch_one_item(monkeypatch)
    monkeypatch.setattr(sync_cmd, "ArticleFetcher", BlockedFetcher)

    stats = asyncio.run(
        sync_cmd._sync_one(
            api=object(),
            account={"biz_id": "biz1", "faker_id": "fake1", "name": "Account A"},
            cfg=GatherConfig(max_pages=1),
            mode="web",
            full=False,
            since_ts=None,
            out_root=tmp_home / "articles",
            no_browser=False,
        )
    )

    article_id = db_store.article_id_for_url(_item()["link"])
    with db_store.connect() as conn:
        row = db_store.get_article(conn, article_id)

    assert stats.failed_articles == 1
    assert row is not None
    assert row["fetch_status"] == "blocked"
    assert row["local_path"] == ""
    assert list((tmp_home / "articles").glob("**/*.md")) == []


def test_sync_custom_out_stores_readable_absolute_path(
    tmp_home: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    class SuccessFetcher:
        async def start(self) -> None:
            pass

        async def close(self) -> None:
            pass

        async def fetch(self, url: str) -> dict[str, Any]:
            return {
                "content": "<p>body</p>",
                "fetch_status": "success",
                "article_type": 0,
                "author": "Author",
                "mp_info": {"mp_name": "Account A"},
            }

    _patch_one_item(monkeypatch)
    monkeypatch.setattr(sync_cmd, "ArticleFetcher", SuccessFetcher)

    out_root = tmp_home / "custom-out"
    asyncio.run(
        sync_cmd._sync_one(
            api=object(),
            account={"biz_id": "biz1", "faker_id": "fake1", "name": "Account A"},
            cfg=GatherConfig(max_pages=1),
            mode="web",
            full=False,
            since_ts=None,
            out_root=out_root,
            no_browser=False,
        )
    )

    article_id = db_store.article_id_for_url(_item()["link"])
    with db_store.connect() as conn:
        row = db_store.get_article(conn, article_id)

    assert row is not None
    assert Path(row["local_path"]).is_absolute()
    assert Path(row["local_path"]).exists()

    article_cmd.read_cmd(article_id, json_output=False)
    assert capsys.readouterr().out.strip() == row["local_path"]


def test_sync_json_error_is_parseable(tmp_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["sync", "missing", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"] == "account_not_found"
