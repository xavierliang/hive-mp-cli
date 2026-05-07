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
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from hive_mp_cli.auth import token as token_store
from hive_mp_cli.wechat.api import WeChatAPI

logger = logging.getLogger(__name__)


class InvalidSessionError(RuntimeError):
    """Raised when the WeChat backend reports an invalid session (re-login required)."""


class FrequencyControlError(RuntimeError):
    """Raised when the backend returns frequency-control code 200013."""


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
    token = token_store.get("token")
    cookie_str = token_store.get("cookie")
    if not token:
        raise InvalidSessionError("No token saved. Run `hive-mp login`.")
    cookie_dict: dict[str, str] = {}
    for pair in (cookie_str or "").split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        cookie_dict[k.strip()] = v.strip()
    api.restore_session(token, cookie_dict)
    return api


def parse_response_status(payload: dict[str, Any]) -> None:
    """Translate ``base_resp.ret`` into our typed exceptions."""
    base = payload.get("base_resp") or {}
    ret = base.get("ret")
    if ret in (None, 0):
        return
    if ret == 200013:
        raise FrequencyControlError("微信触发了频率限制 (200013)")
    if ret == 200003:
        raise InvalidSessionError("登录已失效 (200003)，请重新执行 `hive-mp login`")
    err = base.get("err_msg", str(ret))
    raise RuntimeError(f"微信 API 错误: {err} (ret={ret})")
