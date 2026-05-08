from __future__ import annotations

from pathlib import Path

from hive_mp_cli.wechat import filters
from hive_mp_cli.wechat.parser import html_to_markdown


def _write_rules(yaml_text: str) -> None:
    # Use filters.PATHS (monkey-patched by tmp_home) rather than re-importing
    # PATHS at module top — that binding would point at the un-patched original.
    filters.PATHS.filter_rules_file.write_text(yaml_text, encoding="utf-8")
    filters.reset_cache()


def test_no_rules_file_is_passthrough(tmp_home: Path) -> None:
    html = '<div class="ad">go away</div><p>real</p>'
    assert filters.apply_filter_rules(html) == html


def test_remove_selector(tmp_home: Path) -> None:
    _write_rules(
        """
global:
  remove_selectors:
    - ".reward"
"""
    )
    html = '<section class="reward">tip jar</section><p>body</p>'
    out = filters.apply_filter_rules(html)
    assert "tip jar" not in out
    assert "body" in out


def test_remove_id(tmp_home: Path) -> None:
    _write_rules(
        """
global:
  remove_ids:
    - js_qrcode
"""
    )
    html = '<div id="js_qrcode">scan me</div><p>body</p>'
    out = filters.apply_filter_rules(html)
    assert "scan me" not in out
    assert "body" in out


def test_remove_class(tmp_home: Path) -> None:
    _write_rules(
        """
global:
  remove_classes:
    - rich_media_tool
"""
    )
    html = '<div class="rich_media_tool">share</div><p>body</p>'
    out = filters.apply_filter_rules(html)
    assert "share" not in out
    assert "body" in out


def test_remove_regex(tmp_home: Path) -> None:
    _write_rules(
        """
global:
  remove_regex:
    - "<!-- AD-START -->.*?<!-- AD-END -->"
"""
    )
    html = "<p>body</p><!-- AD-START -->junk\nmore junk<!-- AD-END --><p>more</p>"
    out = filters.apply_filter_rules(html)
    assert "junk" not in out
    assert "body" in out
    assert "more" in out


def test_account_specific_merges_with_global(tmp_home: Path) -> None:
    _write_rules(
        """
global:
  remove_selectors:
    - ".global-noise"
accounts:
  "号A":
    remove_selectors:
      - ".per-account"
"""
    )
    html = (
        '<div class="global-noise">g</div>'
        '<div class="per-account">p</div>'
        "<p>body</p>"
    )
    # No account name → only global rule applies.
    out_anon = filters.apply_filter_rules(html)
    assert "g" not in out_anon
    assert ">p<" in out_anon
    # Matching account → both apply.
    out_a = filters.apply_filter_rules(html, account_name="号A")
    assert "g" not in out_a
    assert ">p<" not in out_a
    assert "body" in out_a
    # Different account → only global applies.
    out_b = filters.apply_filter_rules(html, account_name="号B")
    assert "g" not in out_b
    assert ">p<" in out_b


def test_invalid_yaml_falls_back_to_passthrough(tmp_home: Path) -> None:
    _write_rules("not: valid: yaml: : :")
    html = "<p>body</p>"
    # Falls back silently — never crashes.
    assert filters.apply_filter_rules(html) == html


def test_invalid_regex_does_not_break(tmp_home: Path) -> None:
    _write_rules(
        """
global:
  remove_regex:
    - "([unclosed"
  remove_selectors:
    - ".noise"
"""
    )
    html = '<div class="noise">x</div><p>body</p>'
    out = filters.apply_filter_rules(html)
    # Bad regex is logged and skipped; selector still applies.
    assert "x" not in out
    assert "body" in out


def test_html_to_markdown_applies_filters(tmp_home: Path) -> None:
    """End-to-end sanity: filters fire before markdownify."""
    _write_rules(
        """
global:
  remove_classes:
    - reward_area_personal_new
"""
    )
    html = (
        '<section class="reward_area_personal_new">tip jar text</section>'
        "<p>real body</p>"
    )
    md = html_to_markdown(html)
    assert "tip jar" not in md
    assert "real body" in md
