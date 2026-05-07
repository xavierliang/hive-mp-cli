"""WeChat 公众号平台 HTTP API client.

Ported from we-mp-rss/driver/wx_api.py. Login flow is pure HTTP — no browser
needed; the QR is a server-rendered PNG that the user scans.

Removed from upstream:
- threading.Timer-based async polling (CLI uses a sync loop instead)
- callback-based notifications
- tkinter / static path tied to fork's web UI
- core.print / core.config / Redis hooks
"""
from __future__ import annotations

import logging
import re
import time
import uuid as _uuid
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)


def generate_uuid() -> str:
    return str(_uuid.uuid4()).replace("-", "")


def cookie_expire(cookies: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the most authoritative cookie expiry. Ports driver/cookies.py:expire().

    Returns ``{expiry_timestamp, remaining_seconds, expiry_time}`` so downstream
    code can show a human-readable countdown.
    """
    priority = ["slave_sid", "slave_user", "bizuin", "uin", "pass_ticket"]
    for name in priority:
        for c in cookies:
            if isinstance(c, dict) and c.get("name") == name:
                exp = _extract_expiry(c)
                if exp:
                    return exp
    for c in cookies:
        if isinstance(c, dict):
            exp = _extract_expiry(c)
            if exp:
                return exp
    # Default 2h fallback (matches fork behavior)
    default = time.time() + 7200
    return {
        "expiry_timestamp": default,
        "remaining_seconds": 7200,
        "expiry_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(default)),
    }


def _extract_expiry(cookie: dict[str, Any]) -> dict[str, Any] | None:
    for field in ("expires", "expiry", "expire"):
        if field not in cookie:
            continue
        val = cookie[field]
        ts: float | None = None
        if isinstance(val, (int, float)):
            ts = float(val)
        elif isinstance(val, str) and val.isdigit():
            ts = float(val)
        if ts and ts > time.time():
            return {
                "expiry_timestamp": ts,
                "remaining_seconds": int(ts - time.time()),
                "expiry_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
            }
    return None


@dataclass
class QRSession:
    uuid: str
    qr_url: str
    image_bytes: bytes
    fingerprint: str


_LOGIN_OK_INDICATORS = (
    "wx_app_name", "user_name", "nick_name", "head_img", "account_list", "data_ticket",
)
_LOGIN_FAIL_INDICATORS = (
    "请重新登录", "登录超时", "session过期", "invalid session", "请扫码登录", "loginpage",
)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://mp.weixin.qq.com/",
}


class WeChatAPI:
    BASE_URL = "https://mp.weixin.qq.com"

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(_DEFAULT_HEADERS)
        self.token: str | None = None
        self.cookies: dict[str, str] = {}
        self.fingerprint = generate_uuid()

    # ------------------------------------------------------------------ login
    def request_qr(self) -> QRSession:
        """GET login page, regex out the QR url + uuid, download the QR PNG."""
        resp = self.session.get(f"{self.BASE_URL}/")
        resp.raise_for_status()

        qr_match = re.search(
            r"(https?://mp\.weixin\.qq\.com/cgi-bin/loginqrcode\?action=getqrcode&param=\d+)",
            resp.text,
        )
        uuid_match = re.search(
            r"""(?:"|')uuid(?:"|')\s*:\s*(?:"|')([^"']+)(?:"|')""",
            resp.text,
        )
        if not (qr_match and uuid_match):
            raise RuntimeError("Failed to parse QR info from mp.weixin.qq.com login page")

        qr_url = qr_match.group(1)
        uuid = uuid_match.group(1)
        img_resp = self.session.get(qr_url)
        img_resp.raise_for_status()

        return QRSession(
            uuid=uuid,
            qr_url=qr_url,
            image_bytes=img_resp.content,
            fingerprint=self.fingerprint,
        )

    def poll_status(self) -> str:
        """One poll of /cgi-bin/scanloginqrcode?action=ask.

        Returns: ``waiting`` / ``scanned`` / ``success`` / ``invalid_session`` / ``error``.
        """
        url = f"{self.BASE_URL}/cgi-bin/scanloginqrcode"
        params = {
            "action": "ask",
            "fingerprint": self.fingerprint,
            "lang": "zh_CN",
            "f": "json",
            "ajax": 1,
        }
        try:
            resp = self.session.get(url, params=params)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("poll_status request failed: %s", exc)
            return "error"

        if not resp.headers.get("content-type", "").startswith("application/json"):
            return "waiting"

        data = resp.json()
        if "invalid session" in str(data).lower():
            return "invalid_session"

        status = data.get("status", 0)
        if status in (1, 3):
            self.cookies = requests.utils.dict_from_cookiejar(self.session.cookies)
            return "success"
        if status in (2, 4):
            return "scanned"
        return "waiting"

    def complete_login(self) -> dict[str, Any]:
        """POST bizlogin to finalize. Must be called after ``poll_status() == 'success'``.

        Returns a dict with ``token`` / ``cookies`` / ``cookies_str`` / ``fingerprint`` /
        ``cookie_list`` (the last suitable for ``cookie_expire``).
        """
        login_data = {
            "userlang": "zh_CN",
            "redirect_url": "",
            "cookie_forbidden": "0",
            "cookie_cleaned": "0",
            "plugin_used": "0",
            "login_type": "3",
            "fingerprint": self.fingerprint,
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        resp = self.session.post(
            f"{self.BASE_URL}/cgi-bin/bizlogin?action=login",
            data=login_data,
        )
        resp.raise_for_status()
        self.cookies = requests.utils.dict_from_cookiejar(self.session.cookies)

        token: str | None = None
        try:
            payload = resp.json()
            redirect_url = payload.get("redirect_url", "")
            m = re.search(r"token=([^&\s\"']+)", redirect_url)
            if m:
                token = m.group(1)
        except (ValueError, KeyError):
            pass
        if not token:
            m = re.search(r"token=([^&\s\"']+)", resp.text)
            if m:
                token = m.group(1)

        self.token = token
        return {
            "token": token or "",
            "cookies": self.cookies,
            "cookies_str": "; ".join(f"{k}={v}" for k, v in self.cookies.items()),
            "fingerprint": self.fingerprint,
            "cookie_list": self._cookies_as_list(),
        }

    # ------------------------------------------------------------------ verify
    def restore_session(self, token: str, cookies: dict[str, str]) -> None:
        self.token = token
        self.cookies = dict(cookies)
        self.session.cookies.update(self.cookies)

    def verify_login(self) -> bool:
        """Hit /cgi-bin/home and check for login indicators in the HTML body."""
        if not self.token:
            return False
        try:
            resp = self.session.get(f"{self.BASE_URL}/cgi-bin/home?token={self.token}")
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("verify_login HTTP failed: %s", exc)
            return False
        if "home" not in resp.url:
            return False
        body = resp.text
        if any(s in body for s in _LOGIN_FAIL_INDICATORS):
            return False
        return any(s in body for s in _LOGIN_OK_INDICATORS)

    # ----------------------------------------------------- search & list
    def search_biz(self, keyword: str, limit: int = 10, offset: int = 0) -> dict[str, Any]:
        """Search public accounts by name. Returns the raw API payload.

        Ports core/wx/base.py:search_Biz.
        """
        if not self.token:
            raise RuntimeError("Not logged in (no token). Run `hive-mp login`.")
        url = f"{self.BASE_URL}/cgi-bin/searchbiz"
        params = {
            "action": "search_biz",
            "begin": offset,
            "count": limit,
            "query": keyword,
            "token": self.token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        resp = self.session.get(url, params=params, headers=self._fix_headers(url))
        resp.raise_for_status()
        return resp.json()

    def list_articles_appmsg(
        self, faker_id: str, begin: int = 0, count: int = 5
    ) -> dict[str, Any]:
        """``api`` mode: ``/cgi-bin/appmsg`` (cleanest format). Ports core/wx/model/api.py."""
        if not self.token:
            raise RuntimeError("Not logged in (no token). Run `hive-mp login`.")
        url = f"{self.BASE_URL}/cgi-bin/appmsg"
        params = {
            "action": "list_ex",
            "begin": begin,
            "count": count,
            "fakeid": faker_id,
            "type": "9",
            "token": self.token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        resp = self.session.get(url, params=params, headers=self._fix_headers(url))
        resp.raise_for_status()
        return resp.json()

    def list_articles_publish(
        self, faker_id: str, begin: int = 0, count: int = 5
    ) -> dict[str, Any]:
        """``web`` / ``app`` mode: ``/cgi-bin/appmsgpublish``. Ports core/wx/model/web.py."""
        if not self.token:
            raise RuntimeError("Not logged in (no token). Run `hive-mp login`.")
        url = f"{self.BASE_URL}/cgi-bin/appmsgpublish"
        params = {
            "sub": "list",
            "sub_action": "list_ex",
            "begin": begin,
            "count": count,
            "fakeid": faker_id,
            "token": self.token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": 1,
        }
        resp = self.session.get(url, params=params, headers=self._fix_headers(url))
        resp.raise_for_status()
        return resp.json()

    def _fix_headers(self, url: str) -> dict[str, str]:
        from hive_mp_cli.wechat.anti_crawler import random_legacy_ua
        headers = dict(self.session.headers)
        headers.update(
            {
                "User-Agent": random_legacy_ua(),
                "Refer": url,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
                "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            }
        )
        return headers

    # --------------------------------------------------------------- helpers
    def _cookies_as_list(self) -> list[dict[str, Any]]:
        out = []
        for c in self.session.cookies:
            item: dict[str, Any] = {
                "name": c.name,
                "value": c.value,
                "domain": c.domain or ".weixin.qq.com",
                "path": c.path or "/",
            }
            if c.expires:
                item["expires"] = c.expires
            out.append(item)
        return out
