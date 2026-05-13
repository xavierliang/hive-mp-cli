"""WeChat article body fetcher. Ported from we-mp-rss/driver/wxarticle.py.

**Key change vs upstream**: ``ArticleFetcher`` reuses one ``PlaywrightController``
session across all article fetches in a sync run. Upstream's per-article
``async with`` pattern launches a fresh browser for every URL — that's the
performance bomb identified in the plan (graceful-crunching-brook.md).
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
from datetime import datetime
from typing import Any

from hive_mp_cli.wechat.browser import PlaywrightController
from hive_mp_cli.wechat.parser import fix_images

logger = logging.getLogger(__name__)


_DELETED_MARKERS = (
    ("当前环境异常，完成验证后即可继续访问", "blocked"),
    ("该内容已被发布者删除", "deleted"),
    ("The content has been deleted by the author.", "deleted"),
    ("内容审核中", "deleted"),
    ("该内容暂时无法查看", "deleted"),
    ("违规无法查看", "deleted"),
    ("Unable to view this content because it violates regulation", "deleted"),
    ("发送失败无法查看", "deleted"),
)


class ArticleFetcher:
    """Stateful fetcher: ``await fetcher.start()`` once, ``fetch(url)`` many times, then ``close()``."""

    def __init__(
        self,
        wait_timeout: int = 10000,
        proxy_url: str | None = None,
        scroll_for_images: bool = True,
    ) -> None:
        self.wait_timeout = wait_timeout
        self.proxy_url = proxy_url
        self.scroll_for_images = scroll_for_images
        self.controller: PlaywrightController | None = None

    async def start(self) -> None:
        if self.controller is None:
            self.controller = PlaywrightController(proxy_url=self.proxy_url, mobile_mode=True)
            await self.controller.start()

    async def close(self) -> None:
        if self.controller:
            await self.controller.close()
            self.controller = None

    async def __aenter__(self) -> "ArticleFetcher":
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def fetch(self, url: str) -> dict[str, Any]:
        """Fetch one article. Returns a dict with title/author/content/mp_info/etc.

        Reuses the controller's page across calls — call ``start()`` first.
        """
        if self.controller is None:
            await self.start()
        assert self.controller is not None

        info: dict[str, Any] = {
            "id": self.extract_id_from_url(url),
            "url": url,
            "title": "",
            "author": "",
            "description": "",
            "topic_image": "",
            "publish_time": 0,
            "content": "",
            "mp_info": {"mp_name": "", "logo": "", "biz": ""},
            "mp_id": "",
            "article_type": 0,
            "fetch_error": "",
            "fetch_status": "success",
        }

        ok = await self.controller.open(url, timeout=self.wait_timeout)
        if not ok:
            info["fetch_error"] = "page load failed"
            info["fetch_status"] = "failed"
            return info

        page = self.controller.page
        await asyncio.sleep(2)
        body_text = ""
        try:
            body_text = await page.locator("body").text_content() or ""
        except Exception:
            pass

        for marker, status in _DELETED_MARKERS:
            if marker in body_text:
                info["content"] = ""
                info["fetch_error"] = marker
                info["fetch_status"] = "blocked" if status == "blocked" else "deleted"
                return info

        try:
            info["title"] = (
                await _safe_attr(page, 'meta[property="og:title"]', "content")
                or await page.evaluate("() => document.title")
                or ""
            )
            info["author"] = await _safe_attr(page, 'meta[property="og:article:author"]', "content") or ""
            info["description"] = await _safe_attr(page, 'meta[property="og:description"]', "content") or ""
            info["topic_image"] = await _safe_attr(page, 'meta[property="twitter:image"]', "content") or ""
            info["publish_time"] = await self._extract_publish_time(page)
            info["article_type"] = await self._detect_article_type(page)

            if self.scroll_for_images:
                try:
                    await self._scroll_to_bottom(page)
                except Exception as exc:
                    logger.warning("scroll for images failed: %s", exc)

            content_html = ""
            for selector in ("#js_content", "#js_article"):
                try:
                    html = await page.locator(selector).inner_html()
                    if html:
                        content_html = html
                        break
                except Exception:
                    continue
            info["content"] = fix_images(content_html or "")

            mp_name = ""
            try:
                mp_name = (
                    await page.evaluate(
                        '() => { const el = document.getElementById("js_wx_follow_nickname"); '
                        'return el ? el.textContent : null; }'
                    )
                    or ""
                )
            except Exception:
                pass
            if not mp_name:
                mp_name = await _safe_attr(page, 'meta[property="og:article:author"]', "content") or ""

            logo = ""
            for sel in (
                "#js_like_profile_bar .wx_follow_avatar img",
                "#js_like_profile_bar img.wx_follow_avatar_pic",
                ".wx_follow_avatar img",
            ):
                try:
                    logo = await page.locator(sel).get_attribute("src", timeout=3000)
                    if logo:
                        break
                except Exception:
                    continue
            if not logo:
                logo = await _safe_attr(page, 'meta[property="og:image"]', "content") or ""

            biz = ""
            try:
                biz = await page.evaluate("() => window.biz") or ""
            except Exception:
                biz = ""
            if not biz:
                biz = self._extract_biz(url, content_html or "")

            info["mp_info"] = {"mp_name": mp_name or "未知公众号", "logo": logo or "", "biz": biz or ""}
            if biz:
                try:
                    info["mp_id"] = "MP_WXS_" + base64.b64decode(biz).decode("utf-8")
                except Exception:
                    info["mp_id"] = ""

        except Exception as exc:
            logger.warning("article fetch partial for %s: %s", url, exc)
            info["fetch_error"] = str(exc)
            info["fetch_status"] = "partial"

        return info

    # ----------------------------------------------------- private helpers
    async def _scroll_to_bottom(
        self, page: Any, scroll_step: int = 500, max_scrolls: int = 50, wait_ms: int = 300
    ) -> None:
        total = await page.evaluate("() => document.body.scrollHeight")
        pos = 0
        n = 0
        while pos < total and n < max_scrolls:
            pos += scroll_step
            await page.evaluate(f"() => window.scrollTo(0, {pos})")
            await asyncio.sleep(wait_ms / 1000)
            total = await page.evaluate("() => document.body.scrollHeight")
            n += 1
        await page.evaluate("() => window.scrollTo(0, 0)")
        await asyncio.sleep(0.3)
        await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.7)

    async def _extract_publish_time(self, page: Any) -> int | None:
        """Return the article's publish time as a unix ts, or ``None`` if the
        page didn't expose one. Callers must treat None as "no known time" —
        do not substitute ``now()``: that corrupts ``--since`` filtering and the
        filename date."""
        try:
            txt = await page.locator("#publish_time").text_content()
            if txt:
                parsed = self._parse_time(txt)
                if parsed is not None:
                    return parsed
        except Exception:
            pass
        try:
            content = await page.content()
            for pattern in (
                r'publish_time\s*=\s*["\']([^"\']+)["\']',
                r'var\s+publish_time\s*=\s*["\']([^"\']+)["\']',
                r'create_time\s*=\s*["\']([^"\']+)["\']',
            ):
                m = re.search(pattern, content)
                if m:
                    parsed = self._parse_time(m.group(1))
                    if parsed is not None:
                        return parsed
        except Exception:
            pass
        logger.warning("publish_time not found on page; leaving unset")
        return None

    async def _detect_article_type(self, page: Any) -> int:
        try:
            if await page.evaluate(
                '() => !!document.querySelector(".video_iframe, #js_video_page_title, [data-vid], mp-common-videosnap")'
            ):
                return 5
            if await page.evaluate('() => !!document.querySelector("#js_audio_title, .audio_area, mpvoice")'):
                return 7
            if await page.evaluate('() => !!document.querySelector("#js_text_title")'):
                return 10
            tval = await page.evaluate("() => window.item_show_type")
            if tval is not None:
                ti = int(tval)
                if ti in (0, 5, 7, 10):
                    return ti
            content = await page.content()
            for pattern in (
                r"var\s+itemShowType\s*=\s*window\.a_value_which_never_exists\s*\|\|\s*['\"](\d+)['\"]",
                r"itemShowType\s*=\s*['\"](\d+)['\"]",
                r"item_show_type\s*=\s*['\"](\d+)['\"]",
            ):
                m = re.search(pattern, content)
                if m and int(m.group(1)) in (0, 5, 7, 10):
                    return int(m.group(1))
        except Exception:
            pass
        return 0

    @staticmethod
    def _parse_time(text: str) -> int | None:
        """Parse a WeChat-style date string into a unix ts. ``None`` if no
        format matches — callers must not silently fall back to ``now()``."""
        try:
            normalized = re.sub(
                r"(\d{4})年(\d{1,2})月(\d{1,2})日",
                lambda m: f"{m.group(1)}年{m.group(2).zfill(2)}月{m.group(3).zfill(2)}日",
                text,
            )
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y年%m月%d日 %H:%M",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
                "%Y年%m月%d日",
            ):
                try:
                    return int(datetime.strptime(normalized, fmt).timestamp())
                except ValueError:
                    continue
        except Exception:
            pass
        return None

    @staticmethod
    def _extract_biz(url: str, content: str) -> str:
        m = re.search(r"[?&]__biz=([^&]+)", url)
        if m:
            return m.group(1)
        m = re.search(r'var\s+biz\s*=\s*["\']([^"\']+)["\']', content)
        return m.group(1) if m else ""

    @staticmethod
    def extract_id_from_url(url: str) -> str:
        m = re.search(r"/s/([A-Za-z0-9_-]+)", url)
        if not m:
            return ""
        token = m.group(1)
        padding = 4 - len(token) % 4
        if padding != 4:
            token += "=" * padding
        try:
            return base64.b64decode(token).decode("utf-8")
        except Exception:
            return m.group(1)


async def _safe_attr(page: Any, selector: str, attr: str, timeout: int = 3000) -> str:
    try:
        return await page.locator(selector).get_attribute(attr, timeout=timeout) or ""
    except Exception:
        return ""
