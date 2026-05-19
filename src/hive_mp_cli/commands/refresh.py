from __future__ import annotations

import json as _json

import typer
from rich.console import Console

from hive_mp_cli.auth import refresh as refresh_flow
from hive_mp_cli.config import PATHS
from hive_mp_cli.log import setup as setup_logging
from hive_mp_cli.wechat.api import InvalidSessionError


console = Console(stderr=True)


def refresh_cmd(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Verify refreshability without writing token.json."),
    force: bool = typer.Option(False, "--force", help="Refresh even when the local expiry is not near."),
    if_expiring_within: str | None = typer.Option(
        None,
        "--if-expiring-within",
        help="Only refresh when local expiry is within this duration, e.g. 48h or 30m.",
    ),
) -> None:
    """Refresh the stored WeChat session without QR login."""
    setup_logging(log_dir=PATHS.logs_dir)
    try:
        threshold = refresh_flow.parse_duration(if_expiring_within)
        result = refresh_flow.refresh_session(
            dry_run=dry_run,
            force=force,
            if_expiring_within_seconds=threshold,
        )
    except ValueError as exc:
        payload = {"ok": False, "error": "invalid_duration", "message": str(exc)}
        if json_output:
            typer.echo(_json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            console.print(f"[red]Invalid duration:[/red] {exc}")
        raise typer.Exit(code=1)
    except InvalidSessionError as exc:
        payload = {"ok": False, "error": "login_expired", "message": str(exc)}
        if json_output:
            typer.echo(_json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            console.print(f"[yellow]Login expired.[/yellow] {exc}")
        raise typer.Exit(code=3)
    except RuntimeError as exc:
        payload = {"ok": False, "error": "refresh_failed", "message": str(exc)}
        if json_output:
            typer.echo(_json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            console.print(f"[red]Refresh failed:[/red] {exc}")
        raise typer.Exit(code=2)

    if json_output:
        typer.echo(_json.dumps(result, ensure_ascii=False, indent=2))
        return

    if result.get("skipped"):
        console.print(
            "[green]Refresh skipped.[/green] "
            f"expiry={result.get('old_expiry') or 'unknown'} "
            f"remaining={result.get('remaining_seconds')}s"
        )
        return

    action = "Would refresh" if dry_run else "Refreshed"
    console.print(
        f"[green]{action} session.[/green] "
        f"old_expiry={result.get('old_expiry') or 'unknown'} "
        f"new_expiry={result.get('new_expiry') or 'unknown'} "
        f"extended={result.get('extended_seconds')}s"
    )
