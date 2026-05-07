"""``web`` mode: list articles via /cgi-bin/appmsgpublish. Ports we-mp-rss/core/wx/model/web.py.

Returns the same shape as api_mode (yielding ``aid``, ``title``, ``link``, etc.).
"""
from __future__ import annotations

import json
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
    """Iterate articles via the publish endpoint.

    publish_page returns nested JSON-in-JSON; we unpack ``publish_list`` →
    ``publish_info`` → ``appmsgex`` to get to the article entries.
    """
    i = start_page
    while i < config.max_pages:
        begin = i * config.page_size
        random_sleep(0, config.page_interval, label=f"page-{i + 1}")
        payload = api.list_articles_publish(faker_id, begin=begin, count=config.page_size)

        publish_page_raw = payload.get("publish_page")
        if not publish_page_raw:
            logger.info("web_mode: no more articles after page %d", i + 1)
            break
        try:
            publish_page = json.loads(publish_page_raw) if isinstance(publish_page_raw, str) else publish_page_raw
        except (ValueError, TypeError):
            logger.warning("web_mode: failed to parse publish_page JSON")
            break

        for entry in publish_page.get("publish_list", []):
            info_raw = entry.get("publish_info")
            if not info_raw:
                continue
            try:
                publish_info = json.loads(info_raw) if isinstance(info_raw, str) else info_raw
            except (ValueError, TypeError):
                continue
            for item in publish_info.get("appmsgex", []):
                item.setdefault("id", item.get("aid"))
                item["publish_info"] = publish_info
                yield item
        i += 1
