from __future__ import annotations

import time

import pytest
import requests

from hive_mp_cli.auth import refresh as refresh_flow
from hive_mp_cli.auth import token as token_store
from hive_mp_cli.wechat.api import InvalidSessionError


class _FakeAPI:
    def __init__(self, *, logged_in: bool | None = True, expires: int | None = None) -> None:
        self.token = "tok-refreshed"
        self.logged_in = logged_in
        self.expires = expires or int(time.time()) + 7200
        self.session = requests.Session()
        self.session.cookies.set(
            "slave_sid",
            "new-slave",
            domain="mp.weixin.qq.com",
            path="/",
            expires=self.expires,
        )
        self.session.cookies.set("data_ticket", "new-ticket", domain="mp.weixin.qq.com", path="/")

    def verify_login_status(self) -> dict:
        if self.logged_in is True:
            return {"checked": True, "logged_in": True, "status": "ok"}
        if self.logged_in is False:
            return {"checked": True, "logged_in": False, "status": "login_required"}
        return {"checked": True, "logged_in": None, "status": "unknown"}

    def _cookies_as_list(self) -> list[dict]:
        out = []
        for cookie in self.session.cookies:
            item = {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
            }
            if cookie.expires:
                item["expires"] = cookie.expires
            out.append(item)
        return out


def _save_old_token(expiry_ts: float) -> None:
    token_store.save(
        {
            "token": "tok-old",
            "cookies_str": "slave_sid=old",
            "fingerprint": "fp",
            "expiry": {
                "expiry_timestamp": expiry_ts,
                "remaining_seconds": int(expiry_ts - time.time()),
                "expiry_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expiry_ts)),
            },
        },
        {"wx_app_name": "Test MP"},
    )


def test_parse_duration() -> None:
    assert refresh_flow.parse_duration("48h") == 48 * 3600
    assert refresh_flow.parse_duration("30m") == 30 * 60
    assert refresh_flow.parse_duration("2d") == 2 * 86400
    assert refresh_flow.parse_duration("3600") == 3600


def test_parse_duration_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        refresh_flow.parse_duration("soon")


def test_refresh_session_writes_new_cookie_and_expiry(tmp_home, monkeypatch) -> None:
    old_expiry = time.time() + 1800
    new_expiry = int(time.time()) + 7200
    _save_old_token(old_expiry)
    monkeypatch.setattr(refresh_flow, "make_api_from_token", lambda: _FakeAPI(expires=new_expiry))

    result = refresh_flow.refresh_session()
    saved = token_store.load()

    assert result["refreshed"] is True
    assert result["method"] == "http"
    assert result["new_expiry"] == time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(new_expiry))
    assert saved is not None
    assert saved["token"] == "tok-refreshed"
    assert "slave_sid=new-slave" in saved["cookie"]
    assert saved["cookies"][0]["name"] == "slave_sid"
    assert saved["ext_data"] == {"wx_app_name": "Test MP"}


def test_refresh_session_dry_run_does_not_write(tmp_home, monkeypatch) -> None:
    old_expiry = time.time() + 1800
    _save_old_token(old_expiry)
    monkeypatch.setattr(refresh_flow, "make_api_from_token", lambda: _FakeAPI())

    result = refresh_flow.refresh_session(dry_run=True)
    saved = token_store.load()

    assert result["refreshed"] is True
    assert result["dry_run"] is True
    assert saved is not None
    assert saved["token"] == "tok-old"
    assert saved["cookie"] == "slave_sid=old"


def test_refresh_session_skips_when_not_expiring_soon(tmp_home, monkeypatch) -> None:
    _save_old_token(time.time() + 7 * 86400)

    def fail_if_called():
        raise AssertionError("refresh should not call WeChat when expiry is outside threshold")

    monkeypatch.setattr(refresh_flow, "make_api_from_token", fail_if_called)

    result = refresh_flow.refresh_session(if_expiring_within_seconds=48 * 3600)

    assert result["refreshed"] is False
    assert result["skipped"] is True
    assert result["reason"] == "not_expiring_soon"


def test_refresh_session_raises_when_remote_login_expired(tmp_home, monkeypatch) -> None:
    _save_old_token(time.time() + 1800)
    monkeypatch.setattr(refresh_flow, "make_api_from_token", lambda: _FakeAPI(logged_in=False))

    with pytest.raises(InvalidSessionError):
        refresh_flow.refresh_session()

    saved = token_store.load()
    assert saved is not None
    assert saved["token"] == "tok-old"


def test_refresh_session_requires_token(tmp_home) -> None:
    with pytest.raises(InvalidSessionError):
        refresh_flow.refresh_session()
