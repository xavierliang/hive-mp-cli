"""Anti-crawler config + UA generator + injection script loader.

Ported from we-mp-rss:
- driver/user_agent.py (UA pool with 13 generators across 6 browsers, weighted)
- driver/anti_crawler_config.py (Playwright context + init script)
- driver/anti_crawler_*.js are loaded from sibling files; the inline init script
  in the original was retained as fallback because some Phase D code paths use
  ``AntiCrawlerConfig.get_init_script()`` directly.
"""
from __future__ import annotations

import os
import random
import uuid
from pathlib import Path
from typing import Any

_HEADERS_ACCEPT = [
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
]
_HEADERS_LANG = [
    "zh-CN,zh;q=0.9,en;q=0.8",
    "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
    "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
]
_HEADERS_CACHE = ["no-cache", "max-age=0", "no-store"]


class UserAgentGenerator:
    """Weighted UA pool, ported from we-mp-rss/driver/user_agent.py."""

    MOBILE_WEIGHTS = {"chrome": 0.45, "safari": 0.30, "firefox": 0.10, "edge": 0.08, "opera": 0.05, "qq": 0.02}
    DESKTOP_WEIGHTS = {"chrome": 0.65, "edge": 0.12, "firefox": 0.08, "safari": 0.08, "opera": 0.05, "qq": 0.02}

    def get(self, mobile_mode: bool = True) -> str:
        weights = self.MOBILE_WEIGHTS if mobile_mode else self.DESKTOP_WEIGHTS
        browser = random.choices(list(weights.keys()), weights=list(weights.values()))[0]
        method = f"_{'mobile' if mobile_mode else 'desktop'}_{browser}"
        return getattr(self, method)()

    # version helpers
    def _v_chrome(self) -> str:
        return f"{random.randint(110, 125)}.{random.randint(0, 9)}.{random.randint(4000, 6500)}.{random.randint(0, 200)}"

    def _v_firefox(self) -> str:
        return str(random.randint(110, 125))

    def _v_safari(self) -> str:
        return f"{random.randint(15, 17)}.{random.randint(0, 6)}"

    def _v_edge(self) -> str:
        return f"{random.randint(110, 125)}.{random.randint(0, 9)}.{random.randint(1000, 2500)}.{random.randint(0, 100)}"

    def _v_opera(self) -> str:
        major = random.randint(90, 110)
        return f"{major}.{random.randint(0, 9)}.{random.randint(4000, 5500)}.{major - 13}"

    # OS strings
    def _os_android(self) -> str:
        return random.choices(["10", "11", "12", "13", "14"], weights=[0.15, 0.20, 0.30, 0.25, 0.10])[0]

    def _os_ios(self) -> str:
        return random.choices(
            ["15_0", "15_5", "16_0", "16_5", "17_0", "17_2", "17_4"],
            weights=[0.10, 0.15, 0.15, 0.20, 0.20, 0.15, 0.05],
        )[0]

    def _os_windows(self) -> str:
        return random.choices(
            [
                "Windows NT 10.0; Win64; x64",
                "Windows NT 10.0; WOW64",
                "Windows NT 6.3; Win64; x64",
                "Windows NT 6.1; Win64; x64",
                "Windows NT 11.0; Win64; x64",
            ],
            weights=[0.70, 0.15, 0.08, 0.05, 0.02],
        )[0]

    def _os_macos(self) -> str:
        return random.choices(["10_15_7", "11_0", "12_0", "13_0", "14_0"], weights=[0.25, 0.15, 0.20, 0.25, 0.15])[0]

    def _os_linux(self) -> str:
        return random.choice(
            [
                "X11; Linux x86_64",
                "X11; Ubuntu; Linux x86_64",
                "X11; Fedora; Linux x86_64",
                "X11; Arch Linux; Linux x86_64",
                "X11; Debian; Linux x86_64",
            ]
        )

    def _device_android(self) -> str:
        return random.choice(
            [
                "SM-G991B", "SM-G998B", "SM-G996B", "SM-S908B", "SM-S918B",
                "Mi 13", "Redmi K60", "Xiaomi 14",
                "Pixel 7", "Pixel 8",
                "OnePlus 11",
            ]
        )

    # mobile UA
    def _mobile_chrome(self) -> str:
        return (
            f"Mozilla/5.0 (Linux; Android {self._os_android()}; {self._device_android()}) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{self._v_chrome()} Mobile Safari/537.36"
        )

    def _mobile_safari(self) -> str:
        return (
            f"Mozilla/5.0 (iPhone; CPU iPhone OS {self._os_ios()} like Mac OS X) "
            f"AppleWebKit/605.1.15 (KHTML, like Gecko) Version/{self._v_safari()} Mobile/15E148 Safari/604.1"
        )

    def _mobile_firefox(self) -> str:
        ver = self._v_firefox()
        return f"Mozilla/5.0 (Android {self._os_android()}; Mobile; rv:{ver}.0) Gecko/{ver}.0 Firefox/{ver}.0"

    def _mobile_edge(self) -> str:
        return (
            f"Mozilla/5.0 (Linux; Android {self._os_android()}; {self._device_android()}) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{self._v_chrome()} Mobile Safari/537.36 EdgA/{self._v_edge()}"
        )

    def _mobile_opera(self) -> str:
        return (
            f"Mozilla/5.0 (Linux; Android {self._os_android()}; {self._device_android()}) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{self._v_chrome()} Mobile Safari/537.36 OPR/{self._v_opera()}"
        )

    def _mobile_qq(self) -> str:
        qq_ver = f"{random.randint(13, 15)}.{random.randint(0, 5)}.{random.randint(3000, 3500)}"
        return (
            f"Mozilla/5.0 (Linux; Android {self._os_android()}; {self._device_android()}) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/{self._v_chrome()} "
            f"MQQBrowser/{qq_ver} Mobile Safari/537.36"
        )

    # desktop UA
    def _pick_desktop_os(self, win_w: float, mac_w: float, linux_w: float) -> str:
        return random.choices(
            [self._os_windows(), f"Macintosh; Intel Mac OS X {self._os_macos()}", self._os_linux()],
            weights=[win_w, mac_w, linux_w],
        )[0]

    def _desktop_chrome(self) -> str:
        os_str = self._pick_desktop_os(0.75, 0.15, 0.10)
        return f"Mozilla/5.0 ({os_str}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{self._v_chrome()} Safari/537.36"

    def _desktop_edge(self) -> str:
        return (
            f"Mozilla/5.0 ({self._os_windows()}) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{self._v_chrome()} Safari/537.36 Edg/{self._v_edge()}"
        )

    def _desktop_firefox(self) -> str:
        os_str = self._pick_desktop_os(0.60, 0.25, 0.15)
        ver = self._v_firefox()
        return f"Mozilla/5.0 ({os_str}; rv:{ver}.0) Gecko/20100101 Firefox/{ver}.0"

    def _desktop_safari(self) -> str:
        return (
            f"Mozilla/5.0 (Macintosh; Intel Mac OS X {self._os_macos()}) "
            f"AppleWebKit/605.1.15 (KHTML, like Gecko) Version/{self._v_safari()} Safari/605.1.15"
        )

    def _desktop_opera(self) -> str:
        os_str = self._pick_desktop_os(0.70, 0.20, 0.10)
        return (
            f"Mozilla/5.0 ({os_str}) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{self._v_chrome()} Safari/537.36 OPR/{self._v_opera()}"
        )

    def _desktop_qq(self) -> str:
        qq_ver = f"{random.randint(13, 15)}.{random.randint(0, 5)}.{random.randint(5000, 5500)}"
        return (
            f"Mozilla/5.0 ({self._os_windows()}) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{self._v_chrome()} Safari/537.36 QQBrowser/{qq_ver}"
        )


# Static legacy UA pool — used by HTTP gather (1:1 with we-mp-rss/core/wx/base.py:USER_AGENTS)
LEGACY_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Android 11; Mobile; rv:89.0) Gecko/89.0 Firefox/89.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13.4; rv:109.0) Gecko/20100101 Firefox/114.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Edg/114.0.1823.67",
    "Mozilla/5.0 (Linux; Android 13; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Android 13; Mobile; rv:109.0) Gecko/109.0 Firefox/114.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
]


def random_legacy_ua() -> str:
    return random.choice(LEGACY_USER_AGENTS)


_JS_DIR = Path(__file__).parent
_JS_FILES = ["anti_crawler_base.js", "anti_crawler_advanced.js", "anti_crawler_behavior.js"]


def load_init_script() -> str:
    """Concatenate the 3 anti-crawler JS files into a single Playwright init script."""
    parts = []
    missing = []
    for fname in _JS_FILES:
        path = _JS_DIR / fname
        if path.exists():
            parts.append(f"// === {fname} ===\n" + path.read_text(encoding="utf-8"))
        else:
            missing.append(fname)
    if missing:
        # Surface as a hard error rather than silently degrading to no anti-crawler.
        raise RuntimeError(
            f"Anti-crawler JS files missing from package: {missing}. "
            f"Check wheel build (pyproject.toml force-include)."
        )
    return "\n\n".join(parts)


class AntiCrawlerConfig:
    """Generates Playwright context options + serves the JS init script."""

    TIMEZONES = ["Asia/Shanghai", "Asia/Beijing", "Asia/Hong_Kong", "Asia/Taipei"]
    LOCALES = ["zh-CN", "zh-TW", "zh-HK"]

    def __init__(self) -> None:
        self.ua = UserAgentGenerator()

    def context_options(self, mobile_mode: bool = False) -> dict[str, Any]:
        viewport = (
            {"width": 720, "height": 1920}
            if mobile_mode
            else {"width": random.randint(1200, 1920), "height": random.randint(800, 1080)}
        )
        cfg: dict[str, Any] = {
            "user_agent": self.ua.get(mobile_mode),
            "viewport": viewport,
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "java_script_enabled": True,
            "ignore_https_errors": True,
            "bypass_csp": True,
            "extra_http_headers": self._http_headers(mobile_mode),
        }
        if mobile_mode:
            cfg["extra_http_headers"]["X-Requested-With"] = "com.tencent.mm"
        return cfg

    def _http_headers(self, mobile_mode: bool) -> dict[str, str]:
        headers = {
            "Accept": random.choice(_HEADERS_ACCEPT),
            "Accept-Language": random.choice(_HEADERS_LANG),
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": random.choice(_HEADERS_CACHE),
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
        if mobile_mode:
            headers["X-Requested-With"] = "com.tencent.mm"
        return headers

    @staticmethod
    def init_script() -> str:
        return load_init_script()


def fingerprint() -> str:
    return uuid.uuid4().hex


# Env knobs (1:1 with we-mp-rss)
ENV_CONFIG = {
    "ENABLE_STEALTH": os.getenv("ENABLE_STEALTH", "true").lower() == "true",
    "ENABLE_BEHAVIOR_SIMULATION": os.getenv("ENABLE_BEHAVIOR_SIMULATION", "true").lower() == "true",
    "ENABLE_ADVANCED_DETECTION": os.getenv("ENABLE_ADVANCED_DETECTION", "true").lower() == "true",
    "DETECTION_SENSITIVITY": float(os.getenv("DETECTION_SENSITIVITY", "0.8")),
    "MAX_DETECTION_ATTEMPTS": int(os.getenv("MAX_DETECTION_ATTEMPTS", "10")),
    "BEHAVIOR_SIMULATION_INTERVAL": int(os.getenv("BEHAVIOR_SIMULATION_INTERVAL", "2000")),
    "RANDOM_DELAY_MIN": int(os.getenv("RANDOM_DELAY_MIN", "100")),
    "RANDOM_DELAY_MAX": int(os.getenv("RANDOM_DELAY_MAX", "500")),
}
