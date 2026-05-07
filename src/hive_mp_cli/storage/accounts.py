"""accounts.json CRUD. Single-file, atomic-ish writes.

Schema:
    {"accounts": [{"biz_id": str, "faker_id": str, "name": str,
                    "intro": str, "avatar_url": str,
                    "added_at": int, "last_synced": int | None}]}
"""
from __future__ import annotations

import json
import time
from typing import Any

from hive_mp_cli.config import PATHS


def _read() -> dict[str, Any]:
    if not PATHS.accounts_file.exists():
        return {"accounts": []}
    try:
        data = json.loads(PATHS.accounts_file.read_text(encoding="utf-8"))
        if "accounts" not in data:
            data = {"accounts": []}
        return data
    except (OSError, json.JSONDecodeError):
        return {"accounts": []}


def _write(data: dict[str, Any]) -> None:
    PATHS.home.mkdir(parents=True, exist_ok=True)
    tmp = PATHS.accounts_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PATHS.accounts_file)


def list_all() -> list[dict[str, Any]]:
    return list(_read()["accounts"])


def find(name_or_biz: str) -> dict[str, Any] | None:
    for acc in _read()["accounts"]:
        if acc.get("biz_id") == name_or_biz or acc.get("name") == name_or_biz:
            return acc
    return None


def add(account: dict[str, Any]) -> dict[str, Any]:
    """Insert or update by biz_id."""
    if not account.get("biz_id"):
        raise ValueError("account.biz_id is required")
    data = _read()
    for i, acc in enumerate(data["accounts"]):
        if acc.get("biz_id") == account["biz_id"]:
            merged = {**acc, **account}
            data["accounts"][i] = merged
            _write(data)
            return merged
    new = {
        "added_at": int(time.time()),
        "last_synced": None,
        **account,
    }
    data["accounts"].append(new)
    _write(data)
    return new


def remove(name_or_biz: str) -> bool:
    data = _read()
    before = len(data["accounts"])
    data["accounts"] = [
        a for a in data["accounts"] if a.get("biz_id") != name_or_biz and a.get("name") != name_or_biz
    ]
    if len(data["accounts"]) != before:
        _write(data)
        return True
    return False


def update_last_synced(name_or_biz: str, ts: int | None = None) -> None:
    ts = ts or int(time.time())
    data = _read()
    for acc in data["accounts"]:
        if acc.get("biz_id") == name_or_biz or acc.get("name") == name_or_biz:
            acc["last_synced"] = ts
    _write(data)
