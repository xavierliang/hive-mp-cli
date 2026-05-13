"""Standard logging setup. Replaces fork's `core.print` print_info/print_error/etc."""
from __future__ import annotations

import logging
import os
import re
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from rich.logging import RichHandler

_CONFIGURED = False

# Query-param keys whose values are session secrets and must not be logged.
_SECRET_PARAM_RE = re.compile(
    r"(?P<k>token|key|pass_ticket|fingerprint|uuid|sn|slave_sid|slave_user)=[^&\s'\"]+",
    re.IGNORECASE,
)


def redact_secrets(text: str) -> str:
    """Mask session-bearing query params in a string before logging it."""
    return _SECRET_PARAM_RE.sub(lambda m: f"{m.group('k')}=<redacted>", text)


def safe_exc(exc: BaseException) -> str:
    """Render an exception for logs / error payloads without leaking URL tokens.

    ``repr(exc)`` of e.g. ``requests.HTTPError`` includes the full URL with
    ``?token=...`` — we want the type + message only, with secrets masked.
    """
    return redact_secrets(f"{type(exc).__name__}: {exc}")


class _SecureRotatingFileHandler(TimedRotatingFileHandler):
    """TimedRotatingFileHandler that creates each log file mode 0o600.

    The default umask leaves logs world-readable; we host cookies + URLs with
    tokens in there.
    """

    def _open(self) -> Any:
        old_umask = os.umask(0o077)
        try:
            return super()._open()
        finally:
            os.umask(old_umask)


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
        file_handler = _SecureRotatingFileHandler(
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
