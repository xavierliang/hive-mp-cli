from __future__ import annotations

import json as _json

import typer
from rich.console import Console

from hive_mp_cli.auth import token as token_store
from hive_mp_cli.wechat.gather.base import InvalidSessionError, make_api_from_token

# stderr so JSON output on stdout stays clean.
console = Console(stderr=True)


def status_cmd(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON to stdout."),
    verify_remote: bool = typer.Option(
        True,
        "--verify/--local-only",
        help="Verify the stored session against mp.weixin.qq.com.",
    ),
) -> None:
    """Show login status and token expiry."""
    info = token_store.status()
    info["local_logged_in"] = bool(info.get("logged_in"))

    exit_code = 0
    if info["local_logged_in"] and verify_remote:
        try:
            api = make_api_from_token()
            remote = api.verify_login_status()
        except InvalidSessionError as exc:
            remote = {
                "checked": False,
                "logged_in": False,
                "status": "missing_token",
                "message": str(exc),
            }
        info["remote"] = remote
        if remote.get("logged_in") is True:
            info["logged_in"] = True
        elif remote.get("logged_in") is False:
            info["logged_in"] = False
            info["expired"] = True
            info["remote_expired"] = True
            exit_code = 3
        else:
            info["logged_in"] = False
            info["verification_error"] = True
            exit_code = 2
    elif not info["local_logged_in"]:
        exit_code = 3
    else:
        info["remote"] = {"checked": False, "status": "skipped"}

    if json_output:
        typer.echo(_json.dumps(info, ensure_ascii=False, indent=2))
        if exit_code:
            raise typer.Exit(code=exit_code)
        return

    if not info["local_logged_in"]:
        console.print("[yellow]Not logged in.[/yellow] Run [cyan]hive-mp login[/cyan].")
        raise typer.Exit(code=3)

    expiry = info.get("expiry_time") or "unknown"
    remaining = info.get("remaining_seconds")
    remaining_str = f"{remaining}s" if remaining is not None else "?"

    remote = info.get("remote") or {}
    if remote.get("logged_in") is False:
        console.print(
            f"[yellow]Login expired remotely.[/yellow] local_expiry={expiry} "
            f"remaining={remaining_str}. Run [cyan]hive-mp login[/cyan]."
        )
        raise typer.Exit(code=3)
    if remote.get("logged_in") is None and remote.get("status") not in (None, "skipped"):
        console.print(
            "[yellow]Local token exists, but remote verification failed.[/yellow] "
            f"status={remote.get('status')} message={remote.get('message') or ''}"
        )
        raise typer.Exit(code=2)

    remote_str = "verified" if remote.get("logged_in") is True else "not checked"
    console.print(
        f"[green]Logged in.[/green] token={info['token_preview']} "
        f"expiry={expiry} remaining={remaining_str} remote={remote_str}"
    )
