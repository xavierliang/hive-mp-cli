from __future__ import annotations

import json as _json

import typer
from rich.console import Console

from hive_mp_cli.auth import token as token_store

console = Console()


def status_cmd(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
) -> None:
    """Show login status and token expiry."""
    info = token_store.status()
    if json_output:
        typer.echo(_json.dumps(info, ensure_ascii=False, indent=2))
        if not info["logged_in"]:
            raise typer.Exit(code=3)
        return

    if not info["logged_in"]:
        console.print("[yellow]Not logged in.[/yellow] Run [cyan]hive-mp login[/cyan].")
        raise typer.Exit(code=3)

    expiry = info.get("expiry_time") or "unknown"
    remaining = info.get("remaining_seconds")
    remaining_str = f"{remaining}s" if remaining is not None else "?"
    console.print(
        f"[green]Logged in.[/green] token={info['token_preview']} "
        f"expiry={expiry} remaining={remaining_str}"
    )
