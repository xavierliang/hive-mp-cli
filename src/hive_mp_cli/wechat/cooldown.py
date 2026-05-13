"""Frequency-control cooldown state.

WeChat's 200013 rate limiter is IP+account scoped. Once any account in a sync
run trips it, hammering more accounts only makes things worse. We persist a
cooldown timestamp so the next ``hive-mp sync`` invocation refuses to start
until the cooldown expires.

State file: ``~/.hive-mp/cooldown.json``.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from hive_mp_cli import config as _cfg

logger = logging.getLogger(__name__)

DEFAULT_COOLDOWN_SECONDS = 1800  # 30 min — empirical, matches upstream guidance.


def _state_file():
    # Read PATHS lazily so tests that monkeypatch ``config.PATHS`` (e.g. via
    # ``HIVE_MP_HOME`` redirect in conftest) point at the right tmpdir.
    return _cfg.PATHS.home / "cooldown.json"


def mark_frequency_control(reason: str, seconds: int = DEFAULT_COOLDOWN_SECONDS) -> int:
    """Record a cooldown that expires ``seconds`` from now. Returns the unix ts."""
    until = int(time.time()) + seconds
    _cfg.PATHS.home.mkdir(parents=True, exist_ok=True)
    try:
        _state_file().write_text(
            json.dumps({"until": until, "reason": reason}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("could not persist cooldown state: %s", exc)
    return until


def check_cooldown() -> dict[str, Any] | None:
    """Return ``{until, remaining, reason}`` if a cooldown is active, else None."""
    path = _state_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    until = int(data.get("until") or 0)
    remaining = until - int(time.time())
    if remaining <= 0:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    return {"until": until, "remaining": remaining, "reason": data.get("reason") or ""}


def clear() -> None:
    path = _state_file()
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
