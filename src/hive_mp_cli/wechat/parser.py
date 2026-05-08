"""HTML cleaning + Markdown conversion. Ported from:

- we-mp-rss/core/content_format.py:format_content (markdownify pipeline)
- we-mp-rss/driver/wxarticle.py:Web.fix_images (img/section/p/span attr stripping)
- we-mp-rss/driver/wxarticle.py:Web.proxy_images (image URL preservation)
- we-mp-rss/driver/wxarticle.py:WXArticleFetcher.get_description (text excerpt)

Filter rule plumbing (apis.filter_rule) and htmltools dependency from upstream
were stripped — they belong to the web-UI side.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from bs4 import BeautifulSoup
from markdownify import markdownify as md

from hive_mp_cli.wechat.filters import apply_filter_rules

logger = logging.getLogger(__name__)


def fix_images(content: str) -> str:
    """Restore lazy-loaded image URLs and strip noisy element attributes."""
    if not content:
        return content
    try:
        soup = BeautifulSoup(content, "html.parser")
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src", "")
            if "data:image" in src and src != img.get("data-src", ""):
                src = img.get("data-src", "")
            style = img.get("style", "")
            img.attrs = {}
            if src:
                img["src"] = src
            if style:
                img["style"] = style
        for tag_name in ("section", "p", "span"):
            for tag in soup.find_all(tag_name):
                style = tag.get("style", "")
                tag.attrs = {}
                if style:
                    tag["style"] = style
        return str(soup)
    except Exception as exc:
        logger.warning("fix_images failed: %s", exc)
        return content


def html_to_markdown(content: str, account_name: str | None = None) -> str:
    """Convert WeChat article HTML to Markdown using the markdownify pipeline.

    User-configured filter rules (``~/.hive-mp/filter_rules.yaml``) are applied first
    so noise like ``<section class="reward_area_personal_new">`` never reaches the
    markdown output.
    """
    if not content:
        return ""
    content = apply_filter_rules(content, account_name)
    try:
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup.find_all(["span", "font", "div", "strong", "b"]):
            tag.unwrap()
        for tag in soup.find_all(True):
            for attr in ("style", "class", "data-pm-slice", "data-title"):
                tag.attrs.pop(attr, None)
        cleaned = str(soup)
        cleaned = re.sub(
            r"(<p[^>]*>)([\s\S]*?)(</p>)",
            lambda m: m.group(1) + re.sub(r"\n", "", m.group(2)) + m.group(3),
            cleaned,
        )
        cleaned = re.sub(r"\n\s*\n\s*\n+", "\n", cleaned)
        cleaned = re.sub(r"\*", "", cleaned)

        # Preserve image titles by promoting to alt
        soup = BeautifulSoup(cleaned, "html.parser")
        for img in soup.find_all("img"):
            if "title" in img.attrs:
                img["alt"] = img["title"]
        cleaned = str(soup)

        out = md(cleaned, heading_style="ATX", bullets="-*+", code_language="python")
        return re.sub(r"\n\s*\n\s*\n+", "\n\n", out)
    except Exception as exc:
        logger.warning("html_to_markdown failed: %s", exc)
        return content


def extract_excerpt(content: str, length: int = 200) -> str:
    """Extract a plaintext summary from raw HTML."""
    if not content:
        return ""
    try:
        soup = BeautifulSoup(content, "html.parser")
        text = soup.get_text().strip().strip("\n").replace("\n", " ").replace("\r", " ")
        return text[:length] + "..." if len(text) > length else text
    except Exception:
        return ""


def article_to_markdown(article: dict[str, Any]) -> str:
    """Render a fetched article dict (from ArticleFetcher) into a Markdown document."""
    title = article.get("title", "Untitled")
    author = article.get("author", "")
    mp_name = (article.get("mp_info") or {}).get("mp_name", "")
    publish_time = article.get("publish_time", 0)
    url = article.get("url", "")
    body_html = article.get("content") or ""
    body_md = html_to_markdown(body_html, account_name=mp_name or None)

    if publish_time:
        import time
        date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(publish_time)))
    else:
        date_str = ""

    front: list[str] = ["---"]
    if title:
        front.append(f"title: {_yaml_escape(title)}")
    if author:
        front.append(f"author: {_yaml_escape(author)}")
    if mp_name:
        front.append(f"account: {_yaml_escape(mp_name)}")
    if date_str:
        front.append(f"published: {date_str}")
    if url:
        front.append(f"url: {url}")
    front.append("---")
    front.append("")
    front.append(f"# {title}")
    front.append("")
    front.append(body_md)
    return "\n".join(front)


def _yaml_escape(value: str) -> str:
    if any(ch in value for ch in ":\"'\n#"):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value
