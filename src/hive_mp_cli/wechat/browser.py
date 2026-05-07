"""Async Playwright wrapper. Ported from we-mp-rss/driver/playwright_driver.py.

Key change vs upstream: this controller is built for **session reuse** —
``start_browser`` is called once and ``open_url`` reuses the same context/page
across many article fetches. The fork's per-article ``async with`` pattern is
the performance bomb we removed.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import Any

from hive_mp_cli.wechat.anti_crawler import AntiCrawlerConfig

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logger = logging.getLogger(__name__)


class PlaywrightController:
    """Async Playwright controller with anti-detection scripts injected.

    Args:
        headless: defaults to env HEADLESS=true (set false to debug visually).
        browser_type: ``chromium`` / ``firefox`` / ``webkit``.
        proxy_url: optional proxy URL.
        mobile_mode: applies mobile UA + viewport (the WeChat article path uses this).
    """

    def __init__(
        self,
        headless: bool | None = None,
        browser_type: str = "chromium",
        proxy_url: str | None = None,
        mobile_mode: bool = True,
        debug: bool = False,
    ) -> None:
        import os
        env_headless = os.environ.get("HEADLESS", "true").lower() == "true"
        self.headless = env_headless if headless is None else headless
        self.browser_type = browser_type
        self.proxy_url = proxy_url
        self.mobile_mode = mobile_mode
        self.debug = debug
        self.anti = AntiCrawlerConfig()

        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    @property
    def page(self) -> Any:
        return self._page

    @property
    def context(self) -> Any:
        return self._context

    async def start(self) -> None:
        if self._browser is not None:
            return
        from playwright.async_api import async_playwright

        t0 = time.time()
        self._playwright = await async_playwright().start()
        launcher = getattr(self._playwright, self.browser_type)

        launch_opts: dict[str, Any] = {"headless": self.headless}
        if self.browser_type == "chromium":
            launch_opts["args"] = [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ]
        if self.proxy_url:
            launch_opts["proxy"] = {"server": self.proxy_url}

        self._browser = await launcher.launch(**launch_opts)

        ctx_opts = self.anti.context_options(mobile_mode=self.mobile_mode)
        self._context = await self._browser.new_context(**ctx_opts)
        self._page = await self._context.new_page()

        # Inject the 895 lines of anti-detection JS before any page script runs
        try:
            await self._page.add_init_script(self.anti.init_script())
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to inject anti-crawler script: %s", exc)

        if self.debug:
            logger.info("browser ready in %.2fs (mobile=%s)", time.time() - t0, self.mobile_mode)

    async def open(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000) -> bool:
        if not self.is_ready():
            await self.start()
        try:
            await self._page.goto(url, wait_until=wait_until, timeout=timeout)
            try:
                await self._page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(0.5)
            return True
        except Exception as exc:
            logger.error("open(%s) failed: %s", url, exc)
            return False

    async def content(self) -> str:
        return await self._page.content()

    async def close(self) -> None:
        try:
            if self._page:
                await self._page.close()
                self._page = None
            if self._context:
                await self._context.close()
                self._context = None
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
        except Exception as exc:
            logger.warning("close failed: %s", exc)

    def is_ready(self) -> bool:
        if self._page is None or self._browser is None:
            return False
        try:
            return hasattr(self._page, "_impl_obj") and self._page._impl_obj is not None
        except Exception:
            return False

    async def __aenter__(self) -> "PlaywrightController":
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
