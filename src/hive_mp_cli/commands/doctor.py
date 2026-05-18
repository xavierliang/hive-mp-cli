"""``hive-mp doctor`` — runtime self-check.

Emits a structured health report that an AI agent (or human) can read to figure
out why ``hive-mp sync`` is not behaving. Each check returns one of three
states:

- ``ok``    — healthy
- ``warn``  — degraded but usable (e.g. token expiring soon, low success rate)
- ``fail``  — blocks normal operation (e.g. chromium missing, no accounts)

Exit code: 0 if no checks failed; 1 if any check is ``fail``.
"""
from __future__ import annotations

import json as _json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from hive_mp_cli.auth import token as token_store
from hive_mp_cli.config import PATHS
from hive_mp_cli.storage import accounts as accounts_store
from hive_mp_cli.storage import db as db_store
from hive_mp_cli.storage.accounts import AccountsFileCorrupted
from hive_mp_cli.wechat.gather.base import InvalidSessionError, make_api_from_token

console = Console(stderr=True)

_STATE_ICON = {"ok": "✅", "warn": "⚠️ ", "fail": "❌"}


def doctor_cmd(
    json_output: bool = typer.Option(
        False, "--json", help="Emit JSON to stdout for agent consumption."
    ),
) -> None:
    """Run self-checks and report ✅/⚠️/❌ for each. Exit 1 if anything failed."""
    checks: list[dict[str, Any]] = [
        _check_chromium(),
        _check_login(),
        _check_accounts(),
        _check_sync_health(),
        _check_disk_space(),
    ]

    failed = any(c["status"] == "fail" for c in checks)
    warned = any(c["status"] == "warn" for c in checks)

    if json_output:
        payload = {
            "ok": not failed,
            "summary": "fail" if failed else ("warn" if warned else "ok"),
            "checks": checks,
        }
        typer.echo(_json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for c in checks:
            icon = _STATE_ICON[c["status"]]
            console.print(f"{icon} [bold]{c['name']}[/bold] — {c['message']}")
            if c.get("hint"):
                console.print(f"   [dim]→ {c['hint']}[/dim]")

    if failed:
        raise typer.Exit(code=1)


def _check_chromium() -> dict[str, Any]:
    """Verify Playwright's chromium browser is installed.

    Playwright ships its own browser binary under ``~/Library/Caches/ms-playwright``
    (macOS) or ``~/.cache/ms-playwright`` (Linux). Without it, sync's web mode
    silently falls back to launch errors. We probe via the public API so the
    check survives Playwright internal layout changes.
    """
    try:
        from playwright._impl._driver import compute_driver_executable  # type: ignore
    except Exception:
        # The Playwright package itself isn't installed.
        return {
            "name": "chromium",
            "status": "fail",
            "message": "Playwright Python package not importable.",
            "hint": "Reinstall hive-mp-cli; the playwright dependency is missing.",
        }

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {
            "name": "chromium",
            "status": "fail",
            "message": f"Cannot import playwright.sync_api: {exc}",
            "hint": "Reinstall hive-mp-cli.",
        }

    # Resolve chromium's executable path without launching it. Playwright stores
    # this in the browser's `executable_path` attribute even if the binary file
    # is absent.
    try:
        with sync_playwright() as p:
            exe = p.chromium.executable_path
    except Exception as exc:
        return {
            "name": "chromium",
            "status": "fail",
            "message": f"Could not query chromium path: {exc}",
            "hint": "Run: playwright install chromium",
        }

    if not exe or not Path(exe).exists():
        return {
            "name": "chromium",
            "status": "fail",
            "message": f"Chromium binary not found at {exe or '<unknown>'}.",
            "hint": (
                "Run: playwright install chromium. "
                "In China: PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/ "
                "playwright install chromium"
            ),
        }

    return {
        "name": "chromium",
        "status": "ok",
        "message": f"installed at {exe}",
    }


def _check_login() -> dict[str, Any]:
    """Inspect ~/.hive-mp/token.json and verify the session with WeChat."""
    info = token_store.status()
    if not info.get("logged_in"):
        if info.get("expired"):
            return {
                "name": "login",
                "status": "fail",
                "message": f"Token expired at {info.get('expiry_time') or '?'}.",
                "hint": "Run: hive-mp login",
            }
        return {
            "name": "login",
            "status": "fail",
            "message": "Not logged in.",
            "hint": "Run: hive-mp login",
        }

    remaining = info.get("remaining_seconds")
    if remaining is not None and remaining < 600:
        return {
            "name": "login",
            "status": "warn",
            "message": f"Token expires in {remaining}s.",
            "hint": "Run: hive-mp login (token is about to expire).",
        }

    try:
        remote = make_api_from_token().verify_login_status()
    except InvalidSessionError as exc:
        return {
            "name": "login",
            "status": "fail",
            "message": str(exc),
            "hint": "Run: hive-mp login",
        }

    if remote.get("logged_in") is False:
        return {
            "name": "login",
            "status": "fail",
            "message": f"Remote login verification failed: {remote.get('status')}.",
            "hint": "Run: hive-mp login",
        }
    if remote.get("logged_in") is None:
        return {
            "name": "login",
            "status": "warn",
            "message": f"Remote login verification inconclusive: {remote.get('status')}.",
            "hint": "Check network access to mp.weixin.qq.com, then retry.",
        }

    return {
        "name": "login",
        "status": "ok",
        "message": (
            f"token valid remotely, {remaining}s remaining"
            if remaining is not None
            else "token valid remotely"
        ),
    }


def _check_accounts() -> dict[str, Any]:
    """``accounts.json`` empty = nothing to sync."""
    try:
        accs = accounts_store.list_all()
    except AccountsFileCorrupted as exc:
        return {
            "name": "accounts",
            "status": "fail",
            "message": f"accounts.json is corrupted: {exc}",
            "hint": "Restore the backup created at ~/.hive-mp/accounts.json.corrupted-*",
        }
    if not accs:
        return {
            "name": "accounts",
            "status": "warn",
            "message": "No subscribed accounts.",
            "hint": 'Run: hive-mp account add "<公众号名>"',
        }
    return {
        "name": "accounts",
        "status": "ok",
        "message": f"{len(accs)} subscribed",
    }


def _check_sync_health() -> dict[str, Any]:
    """Sample the last 100 articles' ``has_content`` ratio.

    A persistently low ratio (<50%) means body fetches are getting blocked —
    usually anti-crawler tripping or chromium pages failing to render. This is
    the early-warning signal that a regular sync run will swallow silently.
    """
    if not PATHS.db_file.exists():
        return {
            "name": "sync_health",
            "status": "warn",
            "message": "No articles.db yet — never synced.",
            "hint": "Run: hive-mp sync after adding an account.",
        }

    try:
        with db_store.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            if total == 0:
                return {
                    "name": "sync_health",
                    "status": "warn",
                    "message": "DB exists but has no articles.",
                    "hint": "Run: hive-mp sync",
                }
            row = conn.execute(
                "SELECT COUNT(*) AS n, "
                "SUM(CASE WHEN has_content = 1 THEN 1 ELSE 0 END) AS hits "
                "FROM (SELECT has_content FROM articles "
                "      ORDER BY fetched_at DESC LIMIT 100)"
            ).fetchone()
    except sqlite3.DatabaseError as exc:
        return {
            "name": "sync_health",
            "status": "fail",
            "message": f"articles.db unreadable: {exc}",
            "hint": "Back up ~/.hive-mp/articles.db and delete it to rebuild.",
        }

    n = int(row["n"] or 0)
    hits = int(row["hits"] or 0)
    ratio = hits / n if n else 0.0
    pct = int(ratio * 100)

    if n < 10:
        return {
            "name": "sync_health",
            "status": "ok",
            "message": f"{hits}/{n} recent articles have body (sample too small to judge).",
        }
    if ratio < 0.5:
        return {
            "name": "sync_health",
            "status": "warn",
            "message": f"only {pct}% of last {n} articles have body content.",
            "hint": (
                "Anti-crawler likely tripping. Try: hive-mp sync <name> --repair. "
                "If still low, wait a few hours — frequency control resets per IP+account."
            ),
        }
    return {
        "name": "sync_health",
        "status": "ok",
        "message": f"{pct}% of last {n} articles have body content.",
    }


def _check_disk_space() -> dict[str, Any]:
    """Articles + DB live under ~/.hive-mp/. Warn under 500MB, fail under 50MB."""
    PATHS.home.mkdir(parents=True, exist_ok=True)
    try:
        usage = shutil.disk_usage(PATHS.home)
    except OSError as exc:
        return {
            "name": "disk",
            "status": "warn",
            "message": f"Could not check disk space: {exc}",
        }
    free_mb = usage.free // (1024 * 1024)
    if free_mb < 50:
        return {
            "name": "disk",
            "status": "fail",
            "message": f"Only {free_mb}MB free under {PATHS.home}.",
            "hint": "Free up space before syncing — chromium + articles need room to write.",
        }
    if free_mb < 500:
        return {
            "name": "disk",
            "status": "warn",
            "message": f"{free_mb}MB free under {PATHS.home}.",
        }
    return {
        "name": "disk",
        "status": "ok",
        "message": f"{free_mb}MB free under {PATHS.home}",
    }
