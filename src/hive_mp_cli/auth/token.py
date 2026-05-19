"""Token persistence. Ported from we-mp-rss/driver/token.py.

Saves to ``~/.hive-mp/token.json`` (chmod 600). Redis branch removed; this is a
single-user CLI.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from hive_mp_cli.config import PATHS

logger = logging.getLogger(__name__)


def save(token_data: dict[str, Any], ext_data: dict[str, Any] | None = None) -> None:
    if not token_data.get("token"):
        return
    payload: dict[str, Any] = {
        "token": token_data.get("token", ""),
        "cookie": token_data.get("cookies_str", "") or token_data.get("cookie", ""),
        "fingerprint": token_data.get("fingerprint", ""),
        "expiry": token_data.get("expiry") or {},
    }
    cookies = token_data.get("cookies") or token_data.get("cookie_list")
    if cookies:
        payload["cookies"] = cookies
    ext_payload = ext_data or token_data.get("ext_data")
    if ext_payload:
        payload["ext_data"] = ext_payload
    PATHS.home.mkdir(parents=True, exist_ok=True)
    # umask 0o077 ensures the file is created mode 0o600 even on filesystems
    # where the post-hoc chmod below silently fails (e.g. some network mounts).
    old_umask = os.umask(0o077)
    try:
        PATHS.token_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        os.umask(old_umask)
    try:
        PATHS.token_file.chmod(0o600)
    except OSError as exc:
        logger.warning(
            "Could not chmod %s to 0o600 (%s); token may be world-readable.",
            PATHS.token_file, exc,
        )


def load() -> dict[str, Any] | None:
    if not PATHS.token_file.exists():
        return None
    try:
        return json.loads(PATHS.token_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def get(key: str, default: str = "") -> str:
    data = load()
    if data is None:
        return default
    val = data.get(key, default)
    if isinstance(val, dict):
        return json.dumps(val)
    if val == "None" or val is None:
        return default
    return str(val)


def clear() -> None:
    if PATHS.token_file.exists():
        PATHS.token_file.unlink()


def status() -> dict[str, Any]:
    data = load()
    if not data or not data.get("token"):
        return {"logged_in": False}
    expiry = data.get("expiry") or {}
    expiry_ts = expiry.get("expiry_timestamp")
    remaining = int(expiry_ts - time.time()) if expiry_ts else None
    token_str = data.get("token") or ""
    if remaining is not None and remaining <= 0:
        # Token file is on disk but the timestamp says it's already expired.
        # Treat as logged-out so callers exit with the "login expired" code,
        # while still surfacing the expiry timestamp for debugging.
        return {
            "logged_in": False,
            "expired": True,
            "expiry_time": expiry.get("expiry_time"),
            "remaining_seconds": remaining,
        }
    return {
        "logged_in": True,
        "token_preview": (token_str[:8] + "...") if len(token_str) > 8 else token_str,
        "expiry_time": expiry.get("expiry_time"),
        "remaining_seconds": remaining,
    }
