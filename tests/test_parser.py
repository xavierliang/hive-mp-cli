from __future__ import annotations

from hive_mp_cli.wechat.parser import (
    article_to_markdown,
    extract_excerpt,
    fix_images,
    html_to_markdown,
)


def test_fix_images_promotes_data_src() -> None:
    html = '<img data-src="https://x.com/a.jpg" data-w="100" class="lazy">'
    out = fix_images(html)
    assert 'src="https://x.com/a.jpg"' in out
    assert 'class' not in out
    assert 'data-w' not in out


def test_fix_images_strips_section_attrs() -> None:
    html = '<section class="x" data-foo="1" style="color:red">hi</section>'
    out = fix_images(html)
    assert 'class' not in out
    assert 'data-foo' not in out
    assert 'style="color:red"' in out


def test_html_to_markdown_basic() -> None:
    md = html_to_markdown("<h1>Title</h1><p>hello <b>world</b></p>")
    assert "# Title" in md
    assert "hello world" in md


def test_html_to_markdown_preserves_image_alt_from_title() -> None:
    md = html_to_markdown('<img src="x.jpg" title="Caption">')
    assert "Caption" in md


def test_html_to_markdown_preserves_asterisks_in_text() -> None:
    """`*` in body text must survive — it's load-bearing in code, math, prose.

    markdownify will escape literal ``*`` to ``\\*`` so the markdown renders back
    to a real asterisk; we only care that the character isn't dropped.
    """
    md = html_to_markdown("<p>use **kwargs in Python: a * b = c</p>")
    assert md.count("*") == 3  # **kwargs (2) + a * b (1)


def test_extract_excerpt_truncates() -> None:
    long_html = "<p>" + "a" * 500 + "</p>"
    assert len(extract_excerpt(long_html, length=50)) == 53  # 50 + "..."


def test_extract_excerpt_handles_empty() -> None:
    assert extract_excerpt("") == ""


def test_article_to_markdown_includes_frontmatter() -> None:
    article = {
        "title": "Hello",
        "author": "X",
        "url": "https://mp.weixin.qq.com/s/abc",
        "publish_time": 1700000000,
        "content": "<p>body</p>",
        "mp_info": {"mp_name": "号A"},
    }
    out = article_to_markdown(article)
    assert out.startswith("---")
    assert "title: Hello" in out
    assert "url: https://mp.weixin.qq.com/s/abc" in out
    assert "# Hello" in out
    assert "body" in out
