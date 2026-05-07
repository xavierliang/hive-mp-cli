"""Login orchestration: drive WeChatAPI through QR display + status polling + token save."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from hive_mp_cli.auth import qrcode as qr_render
from hive_mp_cli.auth import token as token_store
from hive_mp_cli.config import PATHS
from hive_mp_cli.wechat.api import WeChatAPI, cookie_expire

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str, str], None]


def perform_login(
    poll_interval: float = 2.0,
    timeout: float = 300.0,
    on_event: StatusCallback | None = None,
) -> dict:
    """Run the full QR login flow synchronously.

    ``on_event(kind, detail)`` is invoked for ``qr_ready`` / ``status`` / ``ascii``
    events. Returns the saved token payload on success; raises ``RuntimeError``
    on timeout / invalid session / parse failure.
    """
    api = WeChatAPI()
    qr = api.request_qr()

    PATHS.ensure()
    qr_path = PATHS.home / "qrcode.png"
    qr_path.write_bytes(qr.image_bytes)
    if on_event:
        on_event("qr_ready", str(qr_path))

    try:
        ascii_art = qr_render.png_to_terminal_ascii(qr_path)
        if on_event:
            on_event("ascii", ascii_art)
    except Exception as exc:
        logger.warning("Could not render QR as ASCII (%s); user can open the PNG directly.", exc)
    qr_render.open_image(qr_path)

    deadline = time.time() + timeout
    last_status: str | None = None
    while time.time() < deadline:
        time.sleep(poll_interval)
        status = api.poll_status()
        if status != last_status:
            last_status = status
            if on_event:
                on_event("status", status)
        if status == "success":
            break
        if status == "invalid_session":
            _cleanup_qr(qr_path)
            raise RuntimeError("Session invalid — please retry login.")
    else:
        _cleanup_qr(qr_path)
        raise RuntimeError(f"Login timed out after {int(timeout)}s.")

    info = api.complete_login()
    if not info["token"]:
        _cleanup_qr(qr_path)
        raise RuntimeError("Login completed but no token was returned.")

    expiry = cookie_expire(info["cookie_list"])
    payload = {
        "token": info["token"],
        "cookies_str": info["cookies_str"],
        "fingerprint": info["fingerprint"],
        "expiry": expiry,
    }
    token_store.save(payload)
    _cleanup_qr(qr_path)
    return payload


def _cleanup_qr(qr_path: Path) -> None:
    try:
        qr_path.unlink()
    except OSError:
        pass
