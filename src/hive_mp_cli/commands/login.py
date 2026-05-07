from __future__ import annotations

import typer
from rich.console import Console

from hive_mp_cli.auth import login as login_flow
from hive_mp_cli.auth import token as token_store
from hive_mp_cli.config import PATHS
from hive_mp_cli.log import setup as setup_logging

console = Console()


def login_cmd() -> None:
    """Scan QR with WeChat, save session token to ~/.hive-mp/token.json."""
    setup_logging(log_dir=PATHS.logs_dir)

    console.print("Fetching QR code from mp.weixin.qq.com...")

    def on_event(kind: str, detail: str) -> None:
        if kind == "qr_ready":
            console.print(f"QR saved to [cyan]{detail}[/cyan]. Scan with WeChat:")
        elif kind == "ascii":
            console.print(detail)
        elif kind == "status":
            label = {
                "waiting": "[dim]waiting for scan...[/dim]",
                "scanned": "[yellow]scanned, please confirm in WeChat[/yellow]",
                "success": "[green]login confirmed[/green]",
                "error": "[red]poll error, retrying[/red]",
            }.get(detail, detail)
            console.print(f"  {label}")

    try:
        login_flow.perform_login(on_event=on_event)
    except RuntimeError as exc:
        console.print(f"[red]Login failed:[/red] {exc}", style="bold")
        raise typer.Exit(code=3)

    s = token_store.status()
    expiry = s.get("expiry_time") or "unknown"
    console.print(f"[green]Logged in.[/green] Token saved (expires: {expiry}).")


def logout_cmd() -> None:
    """Clear stored token."""
    token_store.clear()
    console.print("Logged out. Token file removed.")
