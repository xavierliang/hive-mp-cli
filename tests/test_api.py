from __future__ import annotations

import requests

from hive_mp_cli.wechat.api import WeChatAPI


class _Resp:
    def __init__(self, url: str, text: str = "") -> None:
        self.url = url
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, resp: _Resp | Exception) -> None:
        self.resp = resp
        self.headers = {}

    def get(self, *_args, **_kwargs):
        if isinstance(self.resp, Exception):
            raise self.resp
        return self.resp


def test_verify_login_status_ok() -> None:
    api = WeChatAPI(session=_Session(_Resp("https://mp.weixin.qq.com/cgi-bin/home", "wx_app_name")))
    api.token = "tok"

    out = api.verify_login_status()

    assert out["checked"] is True
    assert out["logged_in"] is True
    assert out["status"] == "ok"


def test_verify_login_status_login_required() -> None:
    api = WeChatAPI(session=_Session(_Resp("https://mp.weixin.qq.com/cgi-bin/home", "请重新登录")))
    api.token = "tok"

    out = api.verify_login_status()

    assert out["checked"] is True
    assert out["logged_in"] is False
    assert out["status"] == "login_required"


def test_verify_login_status_prefers_success_markers_over_loginpage_string() -> None:
    body = "window.__route = 'loginpage'; user_name nick_name head_img"
    api = WeChatAPI(session=_Session(_Resp("https://mp.weixin.qq.com/cgi-bin/home", body)))
    api.token = "tok"

    out = api.verify_login_status()

    assert out["checked"] is True
    assert out["logged_in"] is True
    assert out["status"] == "ok"
    assert "user_name" in out["ok_hits"]


def test_verify_login_status_network_error() -> None:
    api = WeChatAPI(session=_Session(requests.Timeout("boom")))
    api.token = "tok"

    out = api.verify_login_status()

    assert out["checked"] is False
    assert out["logged_in"] is None
    assert out["status"] == "network_error"
