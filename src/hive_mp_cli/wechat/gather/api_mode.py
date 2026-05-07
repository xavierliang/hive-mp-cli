"""``api`` mode: list articles via /cgi-bin/appmsg. Ports we-mp-rss/core/wx/model/api.py.

Yields one article-list-entry dict per article. Caller is responsible for
fetching the full body (HTTP or browser) and persisting.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from hive_mp_cli.wechat.api import WeChatAPI
from hive_mp_cli.wechat.gather.base import GatherConfig, random_sleep

logger = logging.getLogger(__name__)


def list_articles(
    api: WeChatAPI,
    faker_id: str,
    config: GatherConfig,
    start_page: int = 0,
) -> Iterator[dict[str, Any]]:
    """Iterate article-list entries from the public account.

    Each yielded dict contains at minimum ``aid``, ``title``, ``link``, ``create_time``,
    ``update_time``, ``cover``. See we-mp-rss/core/wx/base.py:FillBack for the full
    field reference.
    """
    i = start_page
    while i < config.max_pages:
        begin = i * config.page_size
        random_sleep(0, config.page_interval, label=f"page-{i + 1}")
        payload = api.list_articles_appmsg(faker_id, begin=begin, count=config.page_size)
        items = payload.get("app_msg_list") or []
        if not items:
            logger.info("api_mode: no more articles after page %d", i + 1)
            break
        for item in items:
            item.setdefault("id", item.get("aid"))
            yield item
        i += 1
