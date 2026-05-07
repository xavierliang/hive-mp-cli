"""``hive-mp article ...`` query subcommands."""
from __future__ import annotations

import json as _json
from datetime import datetime

import typer
from rich.console import Console
from rich.table import Table

from hive_mp_cli.config import PATHS
from hive_mp_cli.storage import accounts as accounts_store
from hive_mp_cli.storage import db as db_store

app = typer.Typer(help="Query archived articles.", no_args_is_help=True)
console = Console()


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


@app.command("list")
def list_cmd(
    name_or_biz: str | None = typer.Argument(None, help="Account name or biz_id; omit for all."),
    limit: int = typer.Option(20, "--limit"),
    since: str | None = typer.Option(None, "--since"),
    json_output: bool = typer.Option(False, "--json"),
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
) -> None:
    """Print the local markdown path for an article."""
    with db_store.connect() as conn:
        row = db_store.get_article(conn, article_id)
        if not row:
            # Try prefix match against id
            cur = conn.execute(
                "SELECT * FROM articles WHERE id LIKE ? || '%' LIMIT 2",
                (article_id,),
            ).fetchall()
            if len(cur) == 1:
                row = dict(cur[0])
            elif len(cur) > 1:
                console.print(f"[yellow]Ambiguous id prefix '{article_id}'.[/yellow]")
                raise typer.Exit(code=1)
    if not row:
        console.print(f"[yellow]No such article:[/yellow] {article_id}")
        raise typer.Exit(code=1)
    local = row.get("local_path") or ""
    if not local:
        console.print(f"[yellow]Article has no local markdown (status: {row.get('fetch_status')})[/yellow]")
        raise typer.Exit(code=1)
    full_path = PATHS.articles_dir / local
    typer.echo(str(full_path if full_path.exists() else local))


@app.command("url")
def url_cmd(article_id: str = typer.Argument(...)) -> None:
    """Print the original mp.weixin.qq.com URL for an article."""
    with db_store.connect() as conn:
        row = db_store.get_article(conn, article_id)
        if not row:
            cur = conn.execute(
                "SELECT * FROM articles WHERE id LIKE ? || '%' LIMIT 2",
                (article_id,),
            ).fetchall()
            if len(cur) == 1:
                row = dict(cur[0])
    if not row:
        console.print(f"[yellow]No such article:[/yellow] {article_id}")
        raise typer.Exit(code=1)
    typer.echo(row["url"])


@app.command("search")
def search_cmd(
    keyword: str = typer.Argument(...),
    limit: int = typer.Option(20, "--limit"),
    json_output: bool = typer.Option(False, "--json"),
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
