from __future__ import annotations

from hive_mp_cli.wechat.anti_crawler import (
    AntiCrawlerConfig,
    LEGACY_USER_AGENTS,
    UserAgentGenerator,
    fingerprint,
    load_init_script,
    random_legacy_ua,
)


def test_init_script_concatenates_all_three_files() -> None:
    js = load_init_script()
    assert "anti_crawler_base.js" in js
    assert "anti_crawler_advanced.js" in js
    assert "anti_crawler_behavior.js" in js
    # Spot-check known content from upstream that we copied 1:1
    assert "webdriver" in js  # core property override


def test_user_agent_generator_returns_browser_string() -> None:
    g = UserAgentGenerator()
    for _ in range(20):
        ua = g.get(mobile_mode=True)
        assert ua.startswith("Mozilla/5.0")
    for _ in range(20):
        ua = g.get(mobile_mode=False)
        assert ua.startswith("Mozilla/5.0")


def test_legacy_pool_has_13_entries() -> None:
    # 1:1 with we-mp-rss/core/wx/base.py:USER_AGENTS
    assert len(LEGACY_USER_AGENTS) == 13
    assert random_legacy_ua() in LEGACY_USER_AGENTS


def test_anti_crawler_context_options_includes_required_keys() -> None:
    cfg = AntiCrawlerConfig()
    opts = cfg.context_options(mobile_mode=True)
    assert "user_agent" in opts
    assert opts["viewport"]["width"] > 0
    assert opts["timezone_id"] == "Asia/Shanghai"
    assert opts["bypass_csp"] is True


def test_fingerprint_is_hex_string() -> None:
    fp = fingerprint()
    assert len(fp) == 32
    int(fp, 16)  # valid hex
