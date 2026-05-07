"""``hive-mp sync ...`` — fetch articles for one or all subscribed accounts."""
from __future__ import annotations

import asyncio
import json as _json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console

from hive_mp_cli.config import PATHS
from hive_mp_cli.log import setup as setup_logging
from hive_mp_cli.storage import accounts as accounts_store
from hive_mp_cli.storage import db as db_store
from hive_mp_cli.storage import files as files_store
from hive_mp_cli.wechat.api import WeChatAPI
from hive_mp_cli.wechat.article import ArticleFetcher
from hive_mp_cli.wechat.gather import api_mode, web_mode
from hive_mp_cli.wechat.gather.base import (
    FrequencyControlError,
    GatherConfig,
    GatherStats,
    InvalidSessionError,
    make_api_from_token,
    random_sleep,
)
from hive_mp_cli.wechat.parser import article_to_markdown, extract_excerpt

logger = logging.getLogger(__name__)
console = Console(stderr=True)
_VALID_MODES = {"api", "web"}
_BODY_FAILURE_STATUSES = {"blocked", "deleted", "failed"}
_FAILED_STATUSES = _BODY_FAILURE_STATUSES | {"partial"}


def sync_cmd(
    name_or_biz: str | None = typer.Argument(None, help="Single account to sync. Omit for all."),
    mode: str = typer.Option("web", "--mode", help="api | web (default web — browser fetches body)."),
    full: bool = typer.Option(False, "--full", help="Disable dedup; refetch existing articles."),
    since: str | None = typer.Option(None, "--since", help="ISO date (YYYY-MM-DD) lower bound."),
    max_pages: int = typer.Option(2, "--pages", help="Max list pages per account."),
    out: str | None = typer.Option(None, "--out", help="Override articles output dir."),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Skip body fetching (only catalog metadata). Useful as a smoke test.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Pull article catalog + bodies, write markdown + SQLite metadata."""
    setup_logging(log_dir=PATHS.logs_dir)
    PATHS.ensure()

    if mode not in _VALID_MODES:
        _emit_error(
            json_output,
            "invalid_mode",
            f"--mode must be one of: {', '.join(sorted(_VALID_MODES))}",
            code=1,
            mode=mode,
        )

    out_root = Path(out).expanduser().resolve() if out else PATHS.articles_dir
    out_root.mkdir(parents=True, exist_ok=True)

    targets = _resolve_targets(name_or_biz)
    if not targets:
        target = name_or_biz or "<all>"
        _emit_error(
            json_output,
            "account_not_found",
            f"No subscribed accounts match '{target}'.",
            code=1,
            target=target,
        )

    since_ts = _parse_since(since) if since else None

    try:
        api = make_api_from_token()
    except InvalidSessionError as exc:
        _emit_error(json_output, "login_expired", str(exc), code=3)

    cfg = GatherConfig(max_pages=max_pages)
    aggregate: dict[str, GatherStats] = {}
    for acc in targets:
        if not json_output:
            console.print(f"[bold cyan]→ syncing[/bold cyan] {acc.get('name')}  ({acc.get('biz_id')})")
        try:
            stats = asyncio.run(
                _sync_one(
                    api=api,
                    account=acc,
                    cfg=cfg,
                    mode=mode,
                    full=full,
                    since_ts=since_ts,
                    out_root=out_root,
                    no_browser=no_browser,
                )
            )
        except InvalidSessionError as exc:
            _emit_error(json_output, "login_expired", str(exc), code=3)
        aggregate[acc.get("name", acc.get("biz_id", "?"))] = stats
        if not json_output:
            console.print(
                f"  [green]done[/green] new={stats.new_articles} "
                f"existing={stats.existing_articles} failed={stats.failed_articles}"
            )
        random_sleep(cfg.post_account_min, cfg.post_account_max, label="between accounts")

    if json_output:
        out_payload = {
            name: {
                "new": s.new_articles,
                "existing": s.existing_articles,
                "failed": s.failed_articles,
                "errors": s.errors,
            }
            for name, s in aggregate.items()
        }
        typer.echo(_json.dumps(out_payload, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------- core
async def _sync_one(
    api: WeChatAPI,
    account: dict[str, Any],
    cfg: GatherConfig,
    mode: str,
    full: bool,
    since_ts: int | None,
    out_root: Any,
    no_browser: bool,
) -> GatherStats:
    stats = GatherStats()
    biz_id = account.get("biz_id") or ""
    faker_id = account.get("faker_id") or biz_id
    name = account.get("name") or biz_id

    if not faker_id:
        stats.errors.append("missing faker_id")
        return stats

    fetcher: ArticleFetcher | None = None
    sync_id: int | None = None
    try:
        with db_store.connect() as conn:
            sync_id = db_store.start_sync(conn, biz_id=biz_id, faker_id=faker_id)

            if not no_browser:
                fetcher = ArticleFetcher()
                await fetcher.start()

            entries = list(_iter_list(api, faker_id, cfg, mode))
            stats.pages_fetched = (len(entries) + cfg.page_size - 1) // max(1, cfg.page_size)

            for item in entries:
                url = item.get("link") or ""
                title = item.get("title") or ""
                publish_time = int(item.get("update_time") or item.get("create_time") or 0)
                if since_ts and publish_time and publish_time < since_ts:
                    continue
                if not url:
                    continue

                article_id = db_store.article_id_for_url(url)
                if not full and db_store.has_article(conn, article_id):
                    stats.existing_articles += 1
                    continue

                random_sleep(cfg.pre_article_min, cfg.pre_article_max, label="pre-article")

                body_html = ""
                fetch_status = "metadata-only"
                article_type = 0
                if not no_browser and fetcher is not None:
                    fetched = await fetcher.fetch(url)
                    body_html = fetched.get("content") or ""
                    fetch_status = fetched.get("fetch_status") or "success"
                    article_type = fetched.get("article_type") or 0
                    if fetch_status in _BODY_FAILURE_STATUSES:
                        body_html = ""
                    elif fetch_status == "success" and not body_html:
                        fetch_status = "partial"
                    if fetched.get("title") and not title:
                        title = fetched["title"]
                    if not publish_time and fetched.get("publish_time"):
                        publish_time = int(fetched["publish_time"])
                    article_doc = {
                        "id": article_id,
                        "url": url,
                        "title": title,
                        "author": fetched.get("author") or "",
                        "publish_time": publish_time,
                        "content": body_html,
                        "mp_info": fetched.get("mp_info") or {"mp_name": name},
                    }
                else:
                    article_doc = {
                        "id": article_id,
                        "url": url,
                        "title": title,
                        "author": "",
                        "publish_time": publish_time,
                        "content": "",
                        "mp_info": {"mp_name": name},
                    }

                if body_html:
                    md_text = article_to_markdown(article_doc)
                    md_path = files_store.write_article(
                        out_root, name, publish_time, title, md_text
                    )
                    local_path = _stored_local_path(md_path, out_root)
                else:
                    local_path = ""

                summary = extract_excerpt(body_html or item.get("digest") or "")
                if fetch_status in _FAILED_STATUSES:
                    stats.failed_articles += 1

                row = {
                    "id": article_id,
                    "biz_id": biz_id,
                    "faker_id": faker_id,
                    "url": url,
                    "title": title,
                    "author": article_doc.get("author") or "",
                    "publish_time": publish_time or None,
                    "fetched_at": int(time.time()),
                    "local_path": local_path,
                    "summary": summary,
                    "article_type": article_type,
                    "fetch_status": fetch_status,
                }
                inserted = db_store.upsert_article(conn, row)
                if inserted:
                    stats.new_articles += 1
                else:
                    stats.existing_articles += 1

                random_sleep(cfg.post_article_min, cfg.post_article_max, label="post-article")

            db_store.finish_sync(conn, sync_id, stats.new_articles)
            sync_id = None

        accounts_store.update_last_synced(biz_id or name)
    except FrequencyControlError as exc:
        stats.errors.append(str(exc))
        _finish_sync_after_error(sync_id, stats, str(exc))
        logger.warning("frequency control hit: %s", exc)
    except InvalidSessionError:
        # Let the caller exit with code 3 — token is bad and won't recover this run
        _finish_sync_after_error(sync_id, stats, "login expired")
        raise
    except Exception as exc:
        stats.errors.append(repr(exc))
        _finish_sync_after_error(sync_id, stats, repr(exc))
        logger.exception("sync_one failed for %s", name)
    finally:
        if fetcher is not None:
            await fetcher.close()

    return stats


def _iter_list(api: WeChatAPI, faker_id: str, cfg: GatherConfig, mode: str):
    if mode == "api":
        yield from api_mode.list_articles(api, faker_id, cfg)
    elif mode == "web":
        yield from web_mode.list_articles(api, faker_id, cfg)
    else:
        raise ValueError(f"invalid sync mode: {mode}")


def _emit_error(
    json_output: bool,
    error: str,
    message: str,
    code: int,
    **extra: Any,
) -> NoReturn:
    if json_output:
        payload = {"ok": False, "error": error, "message": message, **extra}
        typer.echo(_json.dumps(payload, ensure_ascii=False))
    else:
        console.print(f"[red]{message}[/red]")
    raise typer.Exit(code=code)


def _stored_local_path(md_path: Path, out_root: Path) -> str:
    try:
        if (
            out_root.resolve() == PATHS.articles_dir.resolve()
            and md_path.is_relative_to(out_root)
        ):
            return str(md_path.relative_to(out_root))
    except OSError:
        pass
    return str(md_path)


def _finish_sync_after_error(sync_id: int | None, stats: GatherStats, error: str) -> None:
    if sync_id is None:
        return
    try:
        with db_store.connect() as conn:
            db_store.finish_sync(conn, sync_id, stats.new_articles, error=error)
    except Exception as exc:
        logger.warning("failed to finish sync log %s after error: %s", sync_id, exc)


def _resolve_targets(name_or_biz: str | None) -> list[dict[str, Any]]:
    if not name_or_biz:
        return accounts_store.list_all()
    found = accounts_store.find(name_or_biz)
    return [found] if found else []


def _parse_since(s: str) -> int:
    try:
        return int(datetime.fromisoformat(s).timestamp())
    except ValueError:
        try:
            return int(datetime.strptime(s, "%Y-%m-%d").timestamp())
        except ValueError as exc:
            raise typer.BadParameter(f"--since: not a valid date: {s}") from exc
