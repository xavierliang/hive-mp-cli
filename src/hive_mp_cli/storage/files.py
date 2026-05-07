"""Markdown file output: ``<articles_root>/<account>/<YYYY-MM-DD>--<slug>.md``."""
from __future__ import annotations

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
    if path.exists():
        # Title collision under same date; append a counter
        stem, ext = path.stem, path.suffix
        for i in range(2, 100):
            alt = folder / f"{stem}--{i}{ext}"
            if not alt.exists():
                path = alt
                break
    path.write_text(body, encoding="utf-8")
    return path
