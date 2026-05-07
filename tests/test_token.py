from __future__ import annotations

import time
from pathlib import Path

from hive_mp_cli.auth import token as token_store
from hive_mp_cli.wechat.api import cookie_expire


def test_save_and_load_round_trip(tmp_home: Path) -> None:
    payload = {
        "token": "abcdef123456",
        "cookies_str": "k1=v1; k2=v2",
        "fingerprint": "fp-xyz",
        "expiry": {"expiry_timestamp": time.time() + 3600},
    }
    token_store.save(payload)
    assert (tmp_home / "token.json").exists()
    loaded = token_store.load()
    assert loaded is not None
    assert loaded["token"] == "abcdef123456"
    assert loaded["cookie"] == "k1=v1; k2=v2"
    assert loaded["fingerprint"] == "fp-xyz"


def test_save_skips_when_no_token(tmp_home: Path) -> None:
    token_store.save({"token": "", "cookies_str": "x=y"})
    assert not (tmp_home / "token.json").exists()


def test_status_when_logged_out(tmp_home: Path) -> None:
    assert token_store.status() == {"logged_in": False}


def test_status_when_logged_in(tmp_home: Path) -> None:
    expiry_ts = time.time() + 1800
    token_store.save(
        {
            "token": "tok-12345678abc",
            "cookies_str": "a=b",
            "fingerprint": "fp",
            "expiry": {
                "expiry_timestamp": expiry_ts,
                "remaining_seconds": 1800,
                "expiry_time": "2026-05-06 12:34:56",
            },
        }
    )
    s = token_store.status()
    assert s["logged_in"] is True
    assert s["token_preview"].startswith("tok-1234")
    assert s["expiry_time"] == "2026-05-06 12:34:56"
    assert 1700 <= (s["remaining_seconds"] or 0) <= 1800


def test_clear_removes_file(tmp_home: Path) -> None:
    token_store.save({"token": "x", "cookies_str": "a=b"})
    assert (tmp_home / "token.json").exists()
    token_store.clear()
    assert not (tmp_home / "token.json").exists()


def test_cookie_expire_picks_priority_cookie() -> None:
    future = int(time.time()) + 7200
    cookies = [
        {"name": "random", "value": "x", "expires": int(time.time()) + 60},
        {"name": "slave_sid", "value": "y", "expires": future},
    ]
    out = cookie_expire(cookies)
    assert out["expiry_timestamp"] == future
    assert out["remaining_seconds"] > 7000


def test_cookie_expire_default_when_none_valid() -> None:
    # All cookies expired or missing expires
    cookies = [{"name": "noop", "value": "x"}]
    out = cookie_expire(cookies)
    assert out["expiry_timestamp"] > time.time()
    assert out["remaining_seconds"] == 7200
