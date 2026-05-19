"""Article gathering orchestrator. Ported from we-mp-rss/core/wx/base.py.

Stripped:
- RSS / Feed model integration
- update_mps (DB write to public-account table)
- FillBack callback / queue.py / send_wx_code

Kept 1:1 (per plan: anti-crawler 1:1):
- Random sleep timing (0-10s page, 1-3s before article, 3-10s after, 3-10s after MP)
- 200013 (frequency control) detection → break
- 200003 (invalid session) detection → raise InvalidSessionError
- UA pool (driver/base.py:USER_AGENTS, 13 entries) via random_legacy_ua()
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field

from hive_mp_cli.auth import token as token_store
from hive_mp_cli.wechat.api import (
    FrequencyControlError,
    InvalidSessionError,
    WeChatAPI,
    parse_response_status,
)

__all__ = [
    "FrequencyControlError",
    "InvalidSessionError",
    "GatherConfig",
    "GatherStats",
    "make_api_from_token",
    "parse_response_status",
    "random_sleep",
]

logger = logging.getLogger(__name__)


@dataclass
class GatherConfig:
    """Sleep budgets — 1:1 with we-mp-rss/core/wx/base.py defaults."""

    page_interval: int = 10           # sleep(0, page_interval) before each list page
    pre_article_min: int = 1
    pre_article_max: int = 3
    post_article_min: int = 3
    post_article_max: int = 10
    post_account_min: int = 3
    post_account_max: int = 10
    max_pages: int = 1
    page_size: int = 5


@dataclass
class GatherStats:
    new_articles: int = 0
    existing_articles: int = 0
    failed_articles: int = 0
    repaired_articles: int = 0
    skipped_dead: int = 0
    pages_fetched: int = 0
    errors: list[str] = field(default_factory=list)


def random_sleep(min_s: int, max_s: int, label: str = "") -> None:
    if max_s <= 0:
        return
    if min_s < 0:
        min_s = 0
    n = random.randint(min_s, max_s)
    if label:
        logger.debug("sleep %ds (%s)", n, label)
    time.sleep(n)


def make_api_from_token() -> WeChatAPI:
    """Construct a WeChatAPI with persisted token + cookie applied."""
    api = WeChatAPI()
    data = token_store.load() or {}
    token = data.get("token") or ""
    cookie_str = data.get("cookie") or ""
    if not token:
        raise InvalidSessionError("No token saved. Run `hive-mp login`.")
    cookies = data.get("cookies") or []
    if isinstance(cookies, list) and cookies:
        api.token = token
        for cookie in cookies:
            if not isinstance(cookie, dict) or not cookie.get("name"):
                continue
            kwargs = {
                "name": cookie.get("name"),
                "value": cookie.get("value", ""),
                "domain": cookie.get("domain") or "mp.weixin.qq.com",
                "path": cookie.get("path") or "/",
            }
            if cookie.get("expires"):
                kwargs["expires"] = cookie["expires"]
            api.session.cookies.set(**kwargs)
        api.cookies = {c.name: c.value for c in api.session.cookies}
        return api

    cookie_dict: dict[str, str] = {}
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        cookie_dict[k.strip()] = v.strip()
    api.restore_session(str(token), cookie_dict)
    return api

