"""accounts.json CRUD. Single-file, atomic-ish writes.

Schema:
    {"accounts": [{"biz_id": str, "faker_id": str, "name": str,
                    "intro": str, "avatar_url": str,
                    "added_at": int, "last_synced": int | None}]}

All read-modify-write paths run under an exclusive ``fcntl.flock`` on a
sibling lock file, so concurrent ``hive-mp account add`` / ``sync``
processes can't lose each other's writes.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import time
from collections.abc import Iterator
from typing import Any

from hive_mp_cli.config import PATHS

logger = logging.getLogger(__name__)


class AccountsFileCorrupted(RuntimeError):
    """Raised when ``accounts.json`` cannot be parsed. The original file is
    renamed to ``accounts.json.corrupted-<ts>`` so users can recover by hand
    without us silently overwriting their data."""


@contextlib.contextmanager
def _locked() -> Iterator[None]:
    """Hold an exclusive lock on accounts.json.lock for the whole RMW cycle."""
    PATHS.home.mkdir(parents=True, exist_ok=True)
    lock_path = PATHS.accounts_file.with_suffix(".json.lock")
    with open(lock_path, "w") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _read() -> dict[str, Any]:
    if not PATHS.accounts_file.exists():
        return {"accounts": []}
    try:
        text = PATHS.accounts_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise AccountsFileCorrupted(
            f"Could not read {PATHS.accounts_file}: {exc}"
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # Quarantine the bad file so the next write doesn't silently overwrite
        # the user's subscription list with an empty array.
        backup = PATHS.accounts_file.with_suffix(f".json.corrupted-{int(time.time())}")
        try:
            PATHS.accounts_file.rename(backup)
        except OSError:
            backup = None
        logger.error(
            "accounts.json is corrupted (parse error at line %d col %d); "
            "moved to %s. Edit it and rename back, or delete to start fresh.",
            exc.lineno, exc.colno, backup,
        )
        raise AccountsFileCorrupted(
            f"accounts.json is corrupted; original kept at {backup}"
        ) from exc
    if not isinstance(data, dict) or "accounts" not in data:
        data = {"accounts": []}
    return data


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
    with _locked():
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
    with _locked():
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
    with _locked():
        data = _read()
        for acc in data["accounts"]:
            if acc.get("biz_id") == name_or_biz or acc.get("name") == name_or_biz:
                acc["last_synced"] = ts
        _write(data)
