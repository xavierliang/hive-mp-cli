"""QR code rendering for terminal + system viewer.

The mp.weixin.qq.com QR is a server-rendered PNG. We can't decode it back to
its underlying URL without a native QR decoder, so we sample its pixels and
render block characters that the user can scan from the terminal.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image


def png_to_terminal_ascii(png_path: Path, target_cells: int = 40) -> str:
    """Render a QR PNG as terminal block characters by pixel sampling.

    Each grid cell becomes ``██`` (dark) or two spaces (light), giving roughly
    square output in a typical monospace font.
    """
    img = Image.open(png_path).convert("L")
    w, h = img.size
    # Trim solid white border (quiet zone) so rendered cells are bigger
    bbox = _content_bbox(img)
    if bbox:
        img = img.crop(bbox)
        w, h = img.size

    cell = max(1, min(w, h) // target_cells)
    cols = w // cell
    rows = h // cell

    lines: list[str] = []
    border_line = "  " * (cols + 4)
    lines.append(border_line)
    lines.append(border_line)
    for r in range(rows):
        row_chars: list[str] = ["  ", "  "]
        for c in range(cols):
            x = c * cell + cell // 2
            y = r * cell + cell // 2
            px = img.getpixel((x, y))
            row_chars.append("██" if px < 128 else "  ")
        row_chars.extend(["  ", "  "])
        lines.append("".join(row_chars))
    lines.append(border_line)
    lines.append(border_line)
    return "\n".join(lines)


def _content_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Return bbox of non-white content; used to strip the QR's quiet zone."""
    inverted = img.point(lambda px: 0 if px > 200 else 255)
    return inverted.getbbox()


def open_image(png_path: Path) -> bool:
    """Best-effort: open the PNG with the OS default viewer. Returns success."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(png_path)], check=False)
        elif sys.platform == "win32":
            import os
            os.startfile(str(png_path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(png_path)], check=False)
        return True
    except Exception:
        return False
