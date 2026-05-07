"""Standard logging setup. Replaces fork's `core.print` print_info/print_error/etc."""
from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler

_CONFIGURED = False


def setup(level: int | str = logging.INFO, log_dir: Path | None = None) -> None:
    """Configure root logger. Idempotent.

    - STDERR gets a Rich-formatted handler for human reading.
    - When ``log_dir`` is provided, a daily rotating file handler is added.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger()
    root.setLevel(level)

    console = RichHandler(
        show_time=True,
        show_level=True,
        show_path=False,
        markup=False,
        rich_tracebacks=True,
    )
    console.setLevel(level)
    root.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            log_dir / "hive-mp.log",
            when="midnight",
            backupCount=14,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        file_handler.setLevel(level)
        root.addHandler(file_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
