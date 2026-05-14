"""``hive-mp sync ...`` — fetch articles for one or all subscribed accounts."""
from __future__ import annotations

import asyncio
import json as _json
import logging
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console

from hive_mp_cli.config import PATHS
from hive_mp_cli.log import safe_exc, setup as setup_logging
from hive_mp_cli.storage import accounts as accounts_store
from hive_mp_cli.storage import db as db_store
from hive_mp_cli.storage import files as files_store
from hive_mp_cli.storage.accounts import AccountsFileCorrupted
from hive_mp_cli.wechat import cooldown
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
# stdout for progress (human + agent watch this). stderr reserved for errors.
out = Console()
# stderr console kept for _emit_error → red error lines on exit !=0.
console = Console(stderr=True)

ProgressCb = Callable[[dict[str, Any]], None]
_VALID_MODES = {"api", "web"}
_BODY_FAILURE_STATUSES = {"blocked", "deleted", "failed"}
_FAILED_STATUSES = _BODY_FAILURE_STATUSES | {"partial"}


def sync_cmd(
    name_or_biz: str | None = typer.Argument(None, help="Single account to sync. Omit for all."),
    mode: str = typer.Option("web", "--mode", help="api | web (default web — browser fetches body)."),
    full: bool = typer.Option(False, "--full", help="Disable dedup; refetch existing articles."),
    repair: bool = typer.Option(
        False,
        "--repair",
        help="Skip list fetch; only retry articles whose body is missing (has_content=0).",
    ),
    since: str | None = typer.Option(None, "--since", help="ISO date (YYYY-MM-DD) lower bound."),
    max_pages: int = typer.Option(2, "--pages", help="Max list pages per account."),
    out: str | None = typer.Option(None, "--out", help="Override articles output dir."),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Skip body fetching (only catalog metadata). Useful as a smoke test.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON to stdout for agent consumption."),
) -> None:
    """Pull article catalog + bodies, write markdown + SQLite metadata."""
    setup_logging(log_dir=PATHS.logs_dir)
    PATHS.ensure()

    active_cooldown = cooldown.check_cooldown()
    if active_cooldown is not None:
        _emit_error(
            json_output,
            "frequency_cooldown",
            f"WeChat frequency control cooldown active "
            f"({active_cooldown['remaining']}s remaining). "
            "Wait before retrying — hammering more requests will extend the block.",
            code=2,
            remaining_seconds=active_cooldown["remaining"],
            reason=active_cooldown["reason"],
        )

    if mode not in _VALID_MODES:
        _emit_error(
            json_output,
            "invalid_mode",
            f"--mode must be one of: {', '.join(sorted(_VALID_MODES))}",
            code=1,
            mode=mode,
        )

    if repair and no_browser:
        _emit_error(
            json_output,
            "incompatible_flags",
            "--repair needs the browser; cannot combine with --no-browser.",
            code=1,
        )

    out_root = Path(out).expanduser().resolve() if out else PATHS.articles_dir
    out_root.mkdir(parents=True, exist_ok=True)

    try:
        targets = _resolve_targets(name_or_biz)
    except AccountsFileCorrupted as exc:
        _emit_error(json_output, "accounts_corrupted", str(exc), code=1)
    if not targets:
        target = name_or_biz or "<all>"
        try:
            available = [a.get("name") or a.get("biz_id") or "" for a in accounts_store.list_all()]
        except AccountsFileCorrupted:
            available = []
        hint = (
            f" Run `hive-mp account list` to see subscribed accounts. "
            f"Currently subscribed: {available}"
            if available
            else " No accounts subscribed yet — `hive-mp account add <name>` to start."
        )
        _emit_error(
            json_output,
            "account_not_found",
            f"No subscribed accounts match '{target}'.{hint}",
            code=1,
            target=target,
            available=available,
        )

    since_ts = _parse_since(since) if since else None

    api: WeChatAPI | None = None
    if not repair:
        # Repair fetches public article URLs via Playwright; the WeChat API token
        # is only needed for list iteration, so we skip the check.
        try:
            api = make_api_from_token()
        except InvalidSessionError as exc:
            _emit_error(json_output, "login_expired", str(exc), code=3)

    cfg = GatherConfig(max_pages=max_pages)
    aggregate: dict[str, tuple[GatherStats, int]] = {}
    final_code = 0
    # In --json mode we stay silent during the run and dump the final blob; in
    # default mode we stream a one-line-per-article progress to stdout so Agents
    # (and humans) can see we're alive. A 10-article sync can take 2-5 minutes
    # of mostly anti-crawler sleeps; without these lines the whole thing looks
    # frozen.
    progress: ProgressCb | None = None if json_output else _make_progress_reporter()
    for acc in targets:
        if not json_output:
            verb = "repairing" if repair else "syncing"
            out.print(f"[bold cyan]→ {verb}[/bold cyan] {acc.get('name')}  ({acc.get('biz_id')})")
        try:
            if repair:
                stats, code = asyncio.run(
                    _repair_one(
                        account=acc, cfg=cfg, out_root=out_root, progress=progress
                    )
                )
            else:
                assert api is not None
                stats, code = asyncio.run(
                    _sync_one(
                        api=api,
                        account=acc,
                        cfg=cfg,
                        mode=mode,
                        full=full,
                        since_ts=since_ts,
                        out_root=out_root,
                        no_browser=no_browser,
                        progress=progress,
                    )
                )
        except InvalidSessionError as exc:
            _emit_error(json_output, "login_expired", str(exc), code=3)
        aggregate[acc.get("name", acc.get("biz_id", "?"))] = (stats, code)
        final_code = max(final_code, code)
        if not json_output:
            out.print(
                f"  [green]done[/green] new={stats.new_articles} "
                f"existing={stats.existing_articles} repaired={stats.repaired_articles} "
                f"failed={stats.failed_articles} skipped_dead={stats.skipped_dead}"
            )
        # If this account tripped 200013, stop hammering. The IP-scoped block
        # affects every other account in the run too — keep walking and we
        # just extend the cooldown window.
        if any("200013" in e or "频率" in e for e in stats.errors):
            reason = next((e for e in stats.errors if "200013" in e or "频率" in e), "200013")
            cooldown.mark_frequency_control(reason=reason)
            if not json_output:
                out.print(
                    "[yellow]frequency control tripped; skipping remaining accounts. "
                    "Cooldown persisted for next run.[/yellow]"
                )
            break
        random_sleep(cfg.post_account_min, cfg.post_account_max, label="between accounts")

    if json_output:
        out_payload = {
            name: {
                "new": s.new_articles,
                "existing": s.existing_articles,
                "repaired": s.repaired_articles,
                "failed": s.failed_articles,
                "skipped_dead": s.skipped_dead,
                "errors": s.errors,
                "exit_code": code,
            }
            for name, (s, code) in aggregate.items()
        }
        typer.echo(_json.dumps(out_payload, ensure_ascii=False, indent=2))

    if final_code != 0:
        raise typer.Exit(code=final_code)


# --------------------------------------------------------------------- core
def _make_progress_reporter() -> ProgressCb:
    """Return a callback that prints one Rich-formatted line per article event.

    Two event shapes: ``{"event": "article_start", "index", "title", "publish_time"}``
    (printed eagerly so an in-flight Playwright hang is visible) and
    ``{"event": "article_done", "index", "fetch_status", "has_content", "duration_s"}``.
    """

    def _fmt_title(title: str | None) -> str:
        t = (title or "[no title]").replace("\n", " ").strip()
        return (t[:38] + "…") if len(t) > 40 else t

    def _fmt_date(ts: int | None) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else "?"

    def report(ev: dict[str, Any]) -> None:
        idx = ev.get("index", "?")
        if ev["event"] == "article_start":
            out.print(
                f"  [dim]\\[{idx}][/dim] {_fmt_date(ev.get('publish_time'))} "
                f"「{_fmt_title(ev.get('title'))}」 [dim]fetching…[/dim]"
            )
        elif ev["event"] == "article_done":
            icon = "[green]✓[/green]" if ev.get("has_content") else "[red]✗[/red]"
            status = ev.get("fetch_status") or "?"
            dur = ev.get("duration_s") or 0.0
            out.print(
                f"  [dim]\\[{idx}][/dim] {_fmt_date(ev.get('publish_time'))} "
                f"「{_fmt_title(ev.get('title'))}」 {icon} {status} "
                f"[dim]({dur:.1f}s)[/dim]"
            )
        elif ev["event"] == "article_skipped":
            out.print(
                f"  [dim]\\[{idx}] skip[/dim] {_fmt_date(ev.get('publish_time'))} "
                f"「{_fmt_title(ev.get('title'))}」 [dim]({ev.get('reason', '')})[/dim]"
            )

    return report


async def _sync_one(
    api: WeChatAPI,
    account: dict[str, Any],
    cfg: GatherConfig,
    mode: str,
    full: bool,
    since_ts: int | None,
    out_root: Any,
    no_browser: bool,
    progress: ProgressCb | None = None,
) -> tuple[GatherStats, int]:
    """Sync one account. Returns ``(stats, exit_code)``.

    ``exit_code``: 0 ok / 2 frequency-control or transient error / 3 login expired.
    Login expired is signalled by re-raising ``InvalidSessionError`` for the caller.
    """
    stats = GatherStats()
    biz_id = account.get("biz_id") or ""
    faker_id = account.get("faker_id") or biz_id
    name = account.get("name") or biz_id

    if not faker_id:
        stats.errors.append("missing faker_id")
        return stats, 1

    fetcher: ArticleFetcher | None = None
    sync_id: int | None = None
    exit_code = 0
    processed = 0
    try:
        with db_store.connect() as conn:
            sync_id = db_store.start_sync(conn, biz_id=biz_id, faker_id=faker_id)

            if not no_browser:
                fetcher = ArticleFetcher()
                await fetcher.start()

            iterator = _iter_list(api, faker_id, cfg, mode)
            while True:
                try:
                    item = next(iterator)
                except StopIteration:
                    break
                except FrequencyControlError as exc:
                    # Page N tripped frequency control. Earlier pages are already
                    # committed (see per-article commit below) — we just stop here.
                    stats.errors.append(str(exc))
                    exit_code = max(exit_code, 2)
                    logger.warning("frequency control during list iteration: %s", exc)
                    break
                except InvalidSessionError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    stats.errors.append(safe_exc(exc))
                    exit_code = max(exit_code, 2)
                    logger.exception("list iteration failed for %s", name)
                    break

                processed += 1
                url = item.get("link") or ""
                title = item.get("title") or ""
                publish_time = int(item.get("update_time") or item.get("create_time") or 0)
                if since_ts and publish_time and publish_time < since_ts:
                    continue
                if not url:
                    continue

                article_id = db_store.article_id_for_url(url)
                prev = db_store.get_article_status(conn, article_id) if not full else None
                if prev is not None and not db_store.should_retry(prev):
                    if (
                        int(prev.get("fetch_attempts") or 0) >= db_store.MAX_FETCH_ATTEMPTS
                        and int(prev.get("has_content") or 0) == 0
                        and prev.get("fetch_status") != "deleted"
                    ):
                        stats.skipped_dead += 1
                    else:
                        stats.existing_articles += 1
                    continue

                # Emit progress eagerly — before the pre-article sleep + Playwright
                # fetch (10-30s typical) — so the agent sees we're alive and knows
                # which article is in flight if anything hangs.
                if progress is not None:
                    progress({
                        "event": "article_start",
                        "index": processed,
                        "title": title,
                        "publish_time": publish_time or None,
                    })
                t_article = time.time()

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
                    "has_content": 1 if body_html else 0,
                }
                inserted = db_store.upsert_article(conn, row)
                # Per-article commit: a later failure in this loop must not roll
                # back articles whose markdown is already on disk.
                conn.commit()
                if inserted:
                    stats.new_articles += 1
                elif body_html and prev is not None and int(prev.get("has_content") or 0) == 0:
                    # Existing row whose body just got filled in → that's a repair.
                    stats.repaired_articles += 1
                else:
                    stats.existing_articles += 1

                if progress is not None:
                    progress({
                        "event": "article_done",
                        "index": processed,
                        "title": title,
                        "publish_time": publish_time or None,
                        "fetch_status": fetch_status,
                        "has_content": bool(body_html),
                        "duration_s": time.time() - t_article,
                    })

                random_sleep(cfg.post_article_min, cfg.post_article_max, label="post-article")

            stats.pages_fetched = (processed + cfg.page_size - 1) // max(1, cfg.page_size)
            db_store.finish_sync(conn, sync_id, stats.new_articles)
            sync_id = None

        accounts_store.update_last_synced(biz_id or name)
    except FrequencyControlError as exc:
        # Reachable only if frequency control is raised outside of next() —
        # e.g. mid-article fetcher call. The inside-loop case is handled above.
        stats.errors.append(str(exc))
        _finish_sync_after_error(sync_id, stats, str(exc))
        logger.warning("frequency control hit: %s", exc)
        exit_code = max(exit_code, 2)
    except InvalidSessionError:
        # Let the caller exit with code 3 — token is bad and won't recover this run
        _finish_sync_after_error(sync_id, stats, "login expired")
        raise
    except Exception as exc:  # noqa: BLE001
        stats.errors.append(safe_exc(exc))
        _finish_sync_after_error(sync_id, stats, safe_exc(exc))
        logger.exception("sync_one failed for %s", name)
        exit_code = max(exit_code, 2)
    finally:
        if fetcher is not None:
            await fetcher.close()

    return stats, exit_code


async def _repair_one(
    account: dict[str, Any],
    cfg: GatherConfig,
    out_root: Path,
    progress: ProgressCb | None = None,
) -> tuple[GatherStats, int]:
    """Refetch bodies for articles where ``has_content=0`` and attempts < cap.

    Returns ``(stats, exit_code)``. ``exit_code`` is 0 on full success, 2 if any
    article fetch failed catastrophically (Playwright crash, etc.).
    """
    stats = GatherStats()
    biz_id = account.get("biz_id") or ""
    faker_id = account.get("faker_id") or biz_id
    name = account.get("name") or biz_id

    if not biz_id:
        stats.errors.append("missing biz_id")
        return stats, 1

    fetcher: ArticleFetcher | None = None
    sync_id: int | None = None
    exit_code = 0
    try:
        with db_store.connect() as conn:
            candidates = db_store.list_repair_candidates(conn, biz_id=biz_id)
            if not candidates:
                logger.info("repair: nothing to do for %s", name)
                return stats, 0

            sync_id = db_store.start_sync(conn, biz_id=biz_id, faker_id=faker_id)
            fetcher = ArticleFetcher()
            await fetcher.start()

            for cand_idx, cand in enumerate(candidates, start=1):
                url = cand.get("url") or ""
                if not url:
                    continue
                if progress is not None:
                    progress({
                        "event": "article_start",
                        "index": cand_idx,
                        "title": cand.get("title") or "",
                        "publish_time": cand.get("publish_time") or None,
                    })
                t_article = time.time()
                random_sleep(cfg.pre_article_min, cfg.pre_article_max, label="pre-article")

                fetched = await fetcher.fetch(url)
                fetch_status = fetched.get("fetch_status") or "success"
                body_html = fetched.get("content") or ""
                if fetch_status in _BODY_FAILURE_STATUSES:
                    body_html = ""
                elif fetch_status == "success" and not body_html:
                    fetch_status = "partial"
                article_type = fetched.get("article_type") or 0
                title = fetched.get("title") or cand.get("title") or ""
                publish_time = int(fetched.get("publish_time") or cand.get("publish_time") or 0)

                article_doc = {
                    "id": cand["id"],
                    "url": url,
                    "title": title,
                    "author": fetched.get("author") or cand.get("author") or "",
                    "publish_time": publish_time,
                    "content": body_html,
                    "mp_info": fetched.get("mp_info") or {"mp_name": name},
                }

                local_path = cand.get("local_path") or ""
                if body_html:
                    md_text = article_to_markdown(article_doc)
                    md_path = files_store.write_article(out_root, name, publish_time, title, md_text)
                    local_path = _stored_local_path(md_path, out_root)

                summary = extract_excerpt(body_html) or cand.get("summary") or ""
                if fetch_status in _FAILED_STATUSES:
                    stats.failed_articles += 1

                row = {
                    "id": cand["id"],
                    "biz_id": biz_id,
                    "faker_id": cand.get("faker_id") or faker_id,
                    "url": url,
                    "title": title,
                    "author": article_doc.get("author") or "",
                    "publish_time": publish_time or None,
                    "fetched_at": int(time.time()),
                    "local_path": local_path,
                    "summary": summary,
                    "article_type": article_type,
                    "fetch_status": fetch_status,
                    "has_content": 1 if body_html else 0,
                }
                db_store.upsert_article(conn, row)
                # Per-article commit: on crash mid-loop, prior repaired rows stick
                # rather than getting rolled back together with the in-flight one.
                conn.commit()
                if body_html:
                    stats.repaired_articles += 1

                if progress is not None:
                    progress({
                        "event": "article_done",
                        "index": cand_idx,
                        "title": title,
                        "publish_time": publish_time or None,
                        "fetch_status": fetch_status,
                        "has_content": bool(body_html),
                        "duration_s": time.time() - t_article,
                    })

                random_sleep(cfg.post_article_min, cfg.post_article_max, label="post-article")

            db_store.finish_sync(conn, sync_id, stats.repaired_articles)
            sync_id = None
    except Exception as exc:  # noqa: BLE001
        stats.errors.append(safe_exc(exc))
        _finish_sync_after_error(sync_id, stats, safe_exc(exc))
        logger.exception("repair_one failed for %s", name)
        exit_code = max(exit_code, 2)
    finally:
        if fetcher is not None:
            await fetcher.close()

    return stats, exit_code


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
