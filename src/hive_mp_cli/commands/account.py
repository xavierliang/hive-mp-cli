"""``hive-mp account ...`` subcommands: add / list / remove / info."""
from __future__ import annotations

import json as _json
import time
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from hive_mp_cli.config import PATHS
from hive_mp_cli.log import setup as setup_logging
from hive_mp_cli.storage import accounts as accounts_store
from hive_mp_cli.storage.accounts import AccountsFileCorrupted
from hive_mp_cli.wechat.api import WeChatAPI
from hive_mp_cli.wechat.gather.base import InvalidSessionError, make_api_from_token

app = typer.Typer(help="Manage subscribed WeChat public accounts.", no_args_is_help=True)
# stderr so JSON / agent-readable output on stdout stays clean.
console = Console(stderr=True)


def _emit_error(
    json_output: bool,
    error: str,
    message: str,
    code: int,
    **extra: Any,
) -> NoReturn:
    """Emit a structured error and exit. JSON path mirrors sync.py:_emit_error."""
    if json_output:
        payload = {"ok": False, "error": error, "message": message, **extra}
        typer.echo(_json.dumps(payload, ensure_ascii=False))
    else:
        console.print(f"[red]{message}[/red]")
    raise typer.Exit(code=code)


def _guard_corruption(json_output: bool) -> None:
    """Catch accounts.json corruption early so callers don't see a traceback."""
    try:
        accounts_store.list_all()
    except AccountsFileCorrupted as exc:
        _emit_error(json_output, "accounts_corrupted", str(exc), code=1)


def _resolve_account(api: WeChatAPI, name_or_biz: str) -> dict | None:
    """Search by keyword and return the first hit's basic fields."""
    payload = api.search_biz(name_or_biz, limit=10)
    items = payload.get("list") or []
    if not items:
        return None
    item = items[0]
    return {
        "biz_id": item.get("fakeid") or item.get("biz_id") or "",
        "faker_id": item.get("fakeid") or item.get("faker_id") or "",
        "name": item.get("nickname") or item.get("name") or "",
        "intro": item.get("signature") or "",
        "avatar_url": item.get("round_head_img") or item.get("logo") or "",
    }


@app.command("add")
def add_cmd(
    name_or_biz: str = typer.Argument(..., help="Public account name or biz_id."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON to stdout for agent consumption."),
) -> None:
    """Search WeChat and add the top match to accounts.json."""
    setup_logging(log_dir=PATHS.logs_dir)
    PATHS.ensure()
    _guard_corruption(json_output)

    existing = accounts_store.find(name_or_biz)
    if existing:
        if json_output:
            payload = {"ok": True, "added": False, "account": existing}
            typer.echo(_json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            console.print(f"[yellow]Already added:[/yellow] {existing['name']} ({existing['biz_id']})")
        return

    try:
        api = make_api_from_token()
    except InvalidSessionError as exc:
        _emit_error(json_output, "login_expired", str(exc), code=3)

    try:
        candidate = _resolve_account(api, name_or_biz)
    except InvalidSessionError as exc:
        _emit_error(json_output, "login_expired", str(exc), code=3)
    except Exception as exc:
        _emit_error(json_output, "search_failed", f"Search failed: {exc}", code=2)

    if not candidate:
        _emit_error(
            json_output,
            "not_found",
            f"No public account matched '{name_or_biz}'.",
            code=1,
            name_or_biz=name_or_biz,
        )
    if not candidate["biz_id"]:
        _emit_error(
            json_output,
            "missing_biz_id",
            "Search hit had no biz_id; cannot add.",
            code=2,
        )

    saved = accounts_store.add(candidate)
    if json_output:
        payload = {"ok": True, "added": True, "account": saved}
        typer.echo(_json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        console.print(f"[green]Added:[/green] {saved['name']} ({saved['biz_id']})")


@app.command("list")
def list_cmd(json_output: bool = typer.Option(False, "--json", help="Emit JSON to stdout for agent consumption.")) -> None:
    """List all subscribed accounts."""
    try:
        accs = accounts_store.list_all()
    except AccountsFileCorrupted as exc:
        _emit_error(json_output, "accounts_corrupted", str(exc), code=1)
    if json_output:
        typer.echo(_json.dumps(accs, ensure_ascii=False, indent=2))
        return
    if not accs:
        console.print("[dim]No accounts. Use `hive-mp account add <name>`.[/dim]")
        return
    table = Table(title="Subscribed accounts")
    table.add_column("name")
    table.add_column("biz_id")
    table.add_column("last synced")
    for acc in accs:
        ls = acc.get("last_synced")
        ls_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(ls)) if ls else "never"
        table.add_row(acc.get("name", ""), acc.get("biz_id", ""), ls_str)
    console.print(table)


@app.command("remove")
def remove_cmd(
    name_or_biz: str = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON to stdout for agent consumption."),
) -> None:
    """Remove a subscribed account."""
    try:
        removed = accounts_store.remove(name_or_biz)
    except AccountsFileCorrupted as exc:
        _emit_error(json_output, "accounts_corrupted", str(exc), code=1)
    if removed:
        if json_output:
            typer.echo(_json.dumps({"ok": True, "removed": name_or_biz}, ensure_ascii=False))
        else:
            console.print(f"[green]Removed[/green] {name_or_biz}")
    else:
        if json_output:
            typer.echo(
                _json.dumps({"ok": False, "error": "not_found", "name": name_or_biz}, ensure_ascii=False)
            )
        else:
            console.print(f"[yellow]Not found:[/yellow] {name_or_biz}")
        raise typer.Exit(code=1)


@app.command("info")
def info_cmd(
    name_or_biz: str = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON to stdout for agent consumption."),
) -> None:
    """Show metadata for a subscribed account."""
    try:
        acc = accounts_store.find(name_or_biz)
    except AccountsFileCorrupted as exc:
        _emit_error(json_output, "accounts_corrupted", str(exc), code=1)
    if not acc:
        _emit_error(
            json_output,
            "not_found",
            f"Not found: {name_or_biz}",
            code=1,
            name_or_biz=name_or_biz,
        )
    if json_output:
        typer.echo(_json.dumps(acc, ensure_ascii=False, indent=2))
    else:
        for k, v in acc.items():
            console.print(f"  [cyan]{k}:[/cyan] {v}")
