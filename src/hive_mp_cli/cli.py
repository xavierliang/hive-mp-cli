from __future__ import annotations

import typer

from hive_mp_cli import __version__
from hive_mp_cli.commands.account import app as account_app
from hive_mp_cli.commands.article import app as article_app
from hive_mp_cli.commands.login import login_cmd, logout_cmd
from hive_mp_cli.commands.status import status_cmd
from hive_mp_cli.commands.sync import sync_cmd

app = typer.Typer(
    name="hive-mp-cli",
    help="Agent-friendly CLI for archiving WeChat Official Account articles to local markdown.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    pass


app.command(name="login")(login_cmd)
app.command(name="logout")(logout_cmd)
app.command(name="status")(status_cmd)
app.command(name="sync")(sync_cmd)
app.add_typer(account_app, name="account")
app.add_typer(article_app, name="article")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
