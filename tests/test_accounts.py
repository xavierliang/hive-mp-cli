from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from hive_mp_cli.cli import app
from hive_mp_cli.storage import accounts as accounts_store


def test_empty_initially(tmp_home: Path) -> None:
    assert accounts_store.list_all() == []


def test_add_and_find(tmp_home: Path) -> None:
    saved = accounts_store.add({"biz_id": "biz1", "name": "公众号A", "faker_id": "fk1"})
    assert saved["biz_id"] == "biz1"
    assert "added_at" in saved
    assert accounts_store.find("biz1")["name"] == "公众号A"
    assert accounts_store.find("公众号A")["biz_id"] == "biz1"
    assert accounts_store.find("nonexistent") is None


def test_add_updates_existing(tmp_home: Path) -> None:
    accounts_store.add({"biz_id": "biz1", "name": "old", "faker_id": "fk1"})
    accounts_store.add({"biz_id": "biz1", "name": "new", "faker_id": "fk1", "intro": "更新"})
    accs = accounts_store.list_all()
    assert len(accs) == 1
    assert accs[0]["name"] == "new"
    assert accs[0]["intro"] == "更新"


def test_remove(tmp_home: Path) -> None:
    accounts_store.add({"biz_id": "biz1", "name": "A", "faker_id": "fk1"})
    accounts_store.add({"biz_id": "biz2", "name": "B", "faker_id": "fk2"})
    assert accounts_store.remove("biz1") is True
    assert len(accounts_store.list_all()) == 1
    assert accounts_store.remove("biz1") is False  # already removed


def test_update_last_synced(tmp_home: Path) -> None:
    accounts_store.add({"biz_id": "biz1", "name": "A", "faker_id": "fk1"})
    accounts_store.update_last_synced("biz1", ts=1700000000)
    acc = accounts_store.find("biz1")
    assert acc["last_synced"] == 1700000000


def test_account_info_json_not_found_is_parseable(tmp_home: Path) -> None:
    """`account info <missing> --json` must emit JSON, not plain text."""
    runner = CliRunner()
    result = runner.invoke(app, ["account", "info", "missing-account", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"] == "not_found"
    assert payload["name_or_biz"] == "missing-account"
