"""``hive-mp article ...`` query subcommands."""
from __future__ import annotations

import json as _json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from hive_mp_cli.config import PATHS
from hive_mp_cli.storage import accounts as accounts_store
from hive_mp_cli.storage import db as db_store

app = typer.Typer(help="Query archived articles.", no_args_is_help=True)
# stderr so machine-readable stdout (`typer.echo(json)`) stays clean.
console = Console(stderr=True)


def _to_date(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s).timestamp())
    except ValueError:
        try:
            return int(datetime.strptime(s, "%Y-%m-%d").timestamp())
        except ValueError as exc:
            raise typer.BadParameter(f"not a date: {s}") from exc


def _resolve_article(conn: sqlite3.Connection, id_or_url: str) -> tuple[dict[str, Any] | None, bool]:
    """Look up an article by id (full or prefix) or full URL.

    Returns ``(row_or_None, ambiguous)``.
    """
    row = db_store.get_article(conn, id_or_url)
    if row:
        return row, False
    cur = conn.execute(
        "SELECT * FROM articles WHERE id LIKE ? || '%' LIMIT 2",
        (id_or_url,),
    ).fetchall()
    if len(cur) == 1:
        return dict(cur[0]), False
    if len(cur) > 1:
        return None, True
    return None, False


@app.command("list")
def list_cmd(
    name_or_biz: str | None = typer.Argument(None, help="Account name or biz_id; omit for all."),
    limit: int = typer.Option(20, "--limit"),
    since: str | None = typer.Option(None, "--since"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON to stdout for agent consumption."),
) -> None:
    """List archived articles."""
    biz_id = None
    if name_or_biz:
        acc = accounts_store.find(name_or_biz)
        if acc:
            biz_id = acc.get("biz_id")
        else:
            biz_id = name_or_biz
    with db_store.connect() as conn:
        rows = db_store.list_articles(conn, biz_id=biz_id, since=_to_date(since), limit=limit)

    if json_output:
        typer.echo(_json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return

    if not rows:
        console.print("[dim]No articles. Run `hive-mp sync` first.[/dim]")
        return

    table = Table()
    table.add_column("id (8c)")
    table.add_column("date")
    table.add_column("title")
    table.add_column("status")
    for r in rows:
        date = (
            datetime.fromtimestamp(int(r["publish_time"])).strftime("%Y-%m-%d")
            if r.get("publish_time")
            else "—"
        )
        table.add_row(r["id"][:8], date, r.get("title") or "", r.get("fetch_status") or "")
    console.print(table)


@app.command("read")
def read_cmd(
    article_id: str = typer.Argument(..., help="Article id (sha256 of url, prefix OK) or full URL."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON to stdout for agent consumption."),
) -> None:
    """Print the local markdown path for an article."""
    with db_store.connect() as conn:
        row, ambiguous = _resolve_article(conn, article_id)

    if ambiguous:
        if json_output:
            typer.echo(
                _json.dumps(
                    {"ok": False, "error": "ambiguous_prefix", "id": article_id}, ensure_ascii=False
                )
            )
        else:
            console.print(f"[yellow]Ambiguous id prefix '{article_id}'.[/yellow]")
        raise typer.Exit(code=1)
    if not row:
        if json_output:
            typer.echo(
                _json.dumps({"ok": False, "error": "not_found", "id": article_id}, ensure_ascii=False)
            )
        else:
            console.print(f"[yellow]No such article:[/yellow] {article_id}")
        raise typer.Exit(code=1)

    local = row.get("local_path") or ""
    if not local:
        if json_output:
            typer.echo(
                _json.dumps(
                    {
                        "ok": False,
                        "error": "no_local_markdown",
                        "id": row["id"],
                        "fetch_status": row.get("fetch_status"),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            console.print(
                f"[yellow]Article has no local markdown (status: {row.get('fetch_status')})[/yellow]"
            )
        raise typer.Exit(code=1)

    local_path = Path(local).expanduser()
    full_path = local_path if local_path.is_absolute() else PATHS.articles_dir / local_path
    final_path = str(full_path if full_path.exists() else local)
    if json_output:
        typer.echo(_json.dumps({"ok": True, "path": final_path}, ensure_ascii=False))
    else:
        typer.echo(final_path)


@app.command("url")
def url_cmd(
    article_id: str = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON to stdout for agent consumption."),
) -> None:
    """Print the original mp.weixin.qq.com URL for an article."""
    with db_store.connect() as conn:
        row, ambiguous = _resolve_article(conn, article_id)

    if ambiguous:
        if json_output:
            typer.echo(
                _json.dumps(
                    {"ok": False, "error": "ambiguous_prefix", "id": article_id}, ensure_ascii=False
                )
            )
        else:
            console.print(f"[yellow]Ambiguous id prefix '{article_id}'.[/yellow]")
        raise typer.Exit(code=1)
    if not row:
        if json_output:
            typer.echo(
                _json.dumps({"ok": False, "error": "not_found", "id": article_id}, ensure_ascii=False)
            )
        else:
            console.print(f"[yellow]No such article:[/yellow] {article_id}")
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(_json.dumps({"ok": True, "url": row["url"]}, ensure_ascii=False))
    else:
        typer.echo(row["url"])


@app.command("search")
def search_cmd(
    keyword: str = typer.Argument(...),
    limit: int = typer.Option(20, "--limit"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON to stdout for agent consumption."),
) -> None:
    """Search archived titles + summaries (LIKE-based)."""
    with db_store.connect() as conn:
        rows = db_store.search_articles(conn, keyword, limit=limit)
    if json_output:
        typer.echo(_json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return
    if not rows:
        console.print("[dim]No matches.[/dim]")
        return
    for r in rows:
        date = (
            datetime.fromtimestamp(int(r["publish_time"])).strftime("%Y-%m-%d")
            if r.get("publish_time")
            else "—"
        )
        console.print(f"  [cyan]{r['id'][:8]}[/cyan]  {date}  {r['title']}")
