"""``hive-mp account ...`` subcommands: search/add/list/remove/info."""
from __future__ import annotations

import json as _json
import time

import typer
from rich.console import Console
from rich.table import Table

from hive_mp_cli.config import PATHS
from hive_mp_cli.log import setup as setup_logging
from hive_mp_cli.storage import accounts as accounts_store
from hive_mp_cli.wechat.api import WeChatAPI
from hive_mp_cli.wechat.gather.base import InvalidSessionError, make_api_from_token

app = typer.Typer(help="Manage subscribed WeChat public accounts.", no_args_is_help=True)
console = Console()


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
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Search WeChat and add the top match to accounts.json."""
    setup_logging(log_dir=PATHS.logs_dir)
    PATHS.ensure()

    existing = accounts_store.find(name_or_biz)
    if existing:
        if json_output:
            typer.echo(_json.dumps(existing, ensure_ascii=False, indent=2))
        else:
            console.print(f"[yellow]Already added:[/yellow] {existing['name']} ({existing['biz_id']})")
        return

    try:
        api = make_api_from_token()
    except InvalidSessionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=3)

    try:
        candidate = _resolve_account(api, name_or_biz)
    except InvalidSessionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=3)
    except Exception as exc:
        console.print(f"[red]Search failed:[/red] {exc}")
        raise typer.Exit(code=2)

    if not candidate:
        console.print(f"[yellow]No public account matched '{name_or_biz}'.[/yellow]")
        raise typer.Exit(code=1)
    if not candidate["biz_id"]:
        console.print("[red]Search hit had no biz_id; cannot add.[/red]")
        raise typer.Exit(code=2)

    saved = accounts_store.add(candidate)
    if json_output:
        typer.echo(_json.dumps(saved, ensure_ascii=False, indent=2))
    else:
        console.print(f"[green]Added:[/green] {saved['name']} ({saved['biz_id']})")


@app.command("list")
def list_cmd(json_output: bool = typer.Option(False, "--json")) -> None:
    """List all subscribed accounts."""
    accs = accounts_store.list_all()
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
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Remove a subscribed account."""
    if accounts_store.remove(name_or_biz):
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
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show metadata for a subscribed account."""
    acc = accounts_store.find(name_or_biz)
    if not acc:
        console.print(f"[yellow]Not found:[/yellow] {name_or_biz}")
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(_json.dumps(acc, ensure_ascii=False, indent=2))
    else:
        for k, v in acc.items():
            console.print(f"  [cyan]{k}:[/cyan] {v}")
