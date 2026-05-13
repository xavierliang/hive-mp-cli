"""Cooldown state machine + auto-clear-on-success behavior."""
from __future__ import annotations

import time
from pathlib import Path

from hive_mp_cli.wechat import cooldown
from hive_mp_cli.wechat.api import WeChatAPI


def test_mark_and_check_roundtrip(tmp_home: Path) -> None:
    until = cooldown.mark_frequency_control("test", seconds=60)
    state = cooldown.check_cooldown()
    assert state is not None
    assert state["until"] == until
    assert 55 <= state["remaining"] <= 60
    assert state["reason"] == "test"


def test_expired_cooldown_auto_deletes(tmp_home: Path) -> None:
    # Write a cooldown that already expired.
    from hive_mp_cli.config import PATHS
    import json
    (PATHS.home / "cooldown.json").write_text(
        json.dumps({"until": int(time.time()) - 10, "reason": "stale"}),
        encoding="utf-8",
    )
    assert cooldown.check_cooldown() is None
    assert not (PATHS.home / "cooldown.json").exists()


def test_successful_api_call_clears_cooldown(tmp_home: Path, monkeypatch) -> None:
    """C choice: any successful WeChat API call wipes a stale cooldown."""
    cooldown.mark_frequency_control("prior trip", seconds=600)
    assert cooldown.check_cooldown() is not None

    api = WeChatAPI()
    api.token = "fake-token"

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        def raise_for_status(self): pass
        def json(self): return {"base_resp": {"ret": 0}, "list": []}

    monkeypatch.setattr(api.session, "get", lambda *a, **kw: FakeResponse())

    api.search_biz("dummy")

    assert cooldown.check_cooldown() is None
