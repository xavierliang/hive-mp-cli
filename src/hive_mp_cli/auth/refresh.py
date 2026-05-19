"""Refresh stored WeChat MP session cookies without starting a QR login flow."""
from __future__ import annotations

import re
import time
from typing import Any

import requests

from hive_mp_cli.auth import token as token_store
from hive_mp_cli.wechat.api import InvalidSessionError, cookie_expire
from hive_mp_cli.wechat.gather.base import make_api_from_token


_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhd]?)\s*$", re.IGNORECASE)
_DURATION_UNITS = {
    "": 1,
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
}


def parse_duration(value: str | None) -> int | None:
    """Parse a small CLI duration such as ``48h`` / ``30m`` / ``3600``."""
    if value is None or value == "":
        return None
    match = _DURATION_RE.match(value)
    if not match:
        raise ValueError(f"Invalid duration: {value!r}. Use values like 48h, 30m, or 3600.")
    amount = int(match.group(1))
    unit = match.group(2).lower()
    return amount * _DURATION_UNITS[unit]


def refresh_session(
    *,
    dry_run: bool = False,
    force: bool = False,
    if_expiring_within_seconds: int | None = None,
) -> dict[str, Any]:
    """Refresh cookies by visiting the MP backend with the stored session.

    This only works while the server-side session is still accepted by WeChat. It
    deliberately does not start QR login or any device automation.
    """
    old = token_store.load()
    if not old or not old.get("token"):
        raise InvalidSessionError("No token saved. Run `hive-mp login`.")

    old_expiry = old.get("expiry") or {}
    old_expiry_ts = old_expiry.get("expiry_timestamp")
    old_remaining = int(old_expiry_ts - time.time()) if old_expiry_ts else None

    if (
        not force
        and if_expiring_within_seconds is not None
        and old_remaining is not None
        and old_remaining > if_expiring_within_seconds
    ):
        return {
            "ok": True,
            "refreshed": False,
            "skipped": True,
            "reason": "not_expiring_soon",
            "method": "http",
            "old_expiry": old_expiry.get("expiry_time"),
            "new_expiry": old_expiry.get("expiry_time"),
            "remaining_seconds": old_remaining,
            "threshold_seconds": if_expiring_within_seconds,
            "dry_run": dry_run,
        }

    api = make_api_from_token()
    remote = api.verify_login_status()
    if remote.get("logged_in") is False:
        raise InvalidSessionError(
            f"WeChat session is no longer accepted ({remote.get('status')}). Run `hive-mp login`."
        )
    if remote.get("logged_in") is not True:
        raise RuntimeError(
            f"WeChat login verification was inconclusive: {remote.get('status')}"
        )

    cookie_list = api._cookies_as_list()
    cookie_dict = requests.utils.dict_from_cookiejar(api.session.cookies)
    expiry = cookie_expire(cookie_list)
    token = api.token or old.get("token") or ""
    payload = {
        "token": token,
        "cookies_str": "; ".join(f"{k}={v}" for k, v in cookie_dict.items()),
        "cookies": cookie_list,
        "fingerprint": old.get("fingerprint", ""),
        "expiry": expiry,
    }

    if not dry_run:
        token_store.save(payload, old.get("ext_data"))

    new_expiry_ts = expiry.get("expiry_timestamp")
    extended_seconds = None
    if old_expiry_ts and new_expiry_ts:
        extended_seconds = int(new_expiry_ts - old_expiry_ts)

    return {
        "ok": True,
        "refreshed": True,
        "skipped": False,
        "method": "http",
        "dry_run": dry_run,
        "verified": True,
        "remote": remote,
        "old_expiry": old_expiry.get("expiry_time"),
        "new_expiry": expiry.get("expiry_time"),
        "old_remaining_seconds": old_remaining,
        "new_remaining_seconds": expiry.get("remaining_seconds"),
        "extended_seconds": extended_seconds,
        "cookie_count": len(cookie_list),
    }
