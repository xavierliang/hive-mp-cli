"""Markdown file output: ``<articles_root>/<account>/<YYYY-MM-DD>--<slug>.md``."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

_UNSAFE_CHARS = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")
_WHITESPACE = re.compile(r"\s+")


def safe_dirname(name: str) -> str:
    name = (name or "unknown").strip() or "unknown"
    name = _UNSAFE_CHARS.sub("_", name)
    name = name.strip(" .")
    return name[:80] or "unknown"


def slugify_title(title: str, max_len: int = 60) -> str:
    title = (title or "untitled").strip() or "untitled"
    title = _UNSAFE_CHARS.sub("", title)
    title = _WHITESPACE.sub("-", title)
    title = title.strip("-.")
    return title[:max_len] or "untitled"


def article_filename(publish_time: int | None, title: str) -> str:
    ts = publish_time or int(time.time())
    date = time.strftime("%Y-%m-%d", time.localtime(int(ts)))
    return f"{date}--{slugify_title(title)}.md"


def write_article(
    articles_root: Path,
    account_name: str,
    publish_time: int | None,
    title: str,
    body: str,
) -> Path:
    folder = articles_root / safe_dirname(account_name)
    folder.mkdir(parents=True, exist_ok=True)
    name = article_filename(publish_time, title)
    path = folder / name
    candidates = [path] + [folder / f"{path.stem}--{i}{path.suffix}" for i in range(2, 100)]
    for candidate in candidates:
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
        except Exception:
            # Don't leave a half-written empty file behind.
            try:
                candidate.unlink()
            except OSError:
                pass
            raise
        return candidate
    raise RuntimeError(f"Could not allocate a unique filename under {folder}")
