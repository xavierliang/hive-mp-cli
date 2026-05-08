"""User-configurable HTML filters for cleaning WeChat article content.

Equivalent of we-mp-rss's ``FilterRule`` table + ``apis/filter_rule.py`` machinery,
but driven by a hand-edited YAML file instead of a database. The YAML lives at
``~/.hive-mp/filter_rules.yaml`` and is optional — missing file means zero
filtering, behavior identical to before this feature was added.

YAML schema::

    global:
      remove_selectors: ["...css..."]   # bs4 .select()
      remove_ids: ["..."]               # bs4 find_all(id=...)
      remove_classes: ["..."]           # bs4 find_all(class_=...)
      remove_regex: ["...regex..."]     # re.sub(pat, '', html, flags=DOTALL)
    accounts:
      "公众号A":                          # matched against accounts.json `name`
        remove_selectors: ["#js_qrcode"]
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from bs4 import BeautifulSoup

from hive_mp_cli.config import PATHS

logger = logging.getLogger(__name__)


@dataclass
class FilterScope:
    remove_selectors: list[str] = field(default_factory=list)
    remove_ids: list[str] = field(default_factory=list)
    remove_classes: list[str] = field(default_factory=list)
    remove_regex: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.remove_selectors or self.remove_ids or self.remove_classes or self.remove_regex)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "FilterScope":
        if not data:
            return cls()
        return cls(
            remove_selectors=list(data.get("remove_selectors") or []),
            remove_ids=list(data.get("remove_ids") or []),
            remove_classes=list(data.get("remove_classes") or []),
            remove_regex=list(data.get("remove_regex") or []),
        )


@dataclass
class FilterRules:
    global_scope: FilterScope = field(default_factory=FilterScope)
    accounts: dict[str, FilterScope] = field(default_factory=dict)

    def for_account(self, account_name: str | None) -> FilterScope:
        """Merge global + account-specific rules. Account scope wins on key collisions
        only by *adding* — we union the lists rather than replacing.
        """
        if not account_name:
            return self.global_scope
        per = self.accounts.get(account_name)
        if per is None:
            return self.global_scope
        return FilterScope(
            remove_selectors=self.global_scope.remove_selectors + per.remove_selectors,
            remove_ids=self.global_scope.remove_ids + per.remove_ids,
            remove_classes=self.global_scope.remove_classes + per.remove_classes,
            remove_regex=self.global_scope.remove_regex + per.remove_regex,
        )

    def is_empty(self) -> bool:
        if not self.global_scope.is_empty():
            return False
        return all(scope.is_empty() for scope in self.accounts.values())


_EMPTY = FilterRules()


@lru_cache(maxsize=1)
def _load_cached(path_str: str, mtime: float) -> FilterRules:
    """LRU-cached load keyed by (path, mtime) so edits invalidate without restart."""
    path = Path(path_str)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("filter_rules: failed to read %s: %s", path, exc)
        return _EMPTY
    if not isinstance(raw, dict):
        logger.warning("filter_rules: top-level must be a mapping, got %s", type(raw).__name__)
        return _EMPTY
    accounts_block = raw.get("accounts") or {}
    accounts: dict[str, FilterScope] = {}
    if isinstance(accounts_block, dict):
        for name, data in accounts_block.items():
            if isinstance(data, dict):
                accounts[str(name)] = FilterScope.from_dict(data)
    return FilterRules(
        global_scope=FilterScope.from_dict(raw.get("global")),
        accounts=accounts,
    )


def load_filter_rules(path: Path | None = None) -> FilterRules:
    """Read ``~/.hive-mp/filter_rules.yaml`` (or the given path). Missing → empty rules."""
    file_path = path or PATHS.filter_rules_file
    if not file_path.exists():
        return _EMPTY
    try:
        mtime = file_path.stat().st_mtime
    except OSError:
        return _EMPTY
    return _load_cached(str(file_path), mtime)


def apply_filter_rules(html: str, account_name: str | None = None) -> str:
    """Strip user-configured noise from raw HTML before markdown conversion.

    No-op if there are no rules or HTML is empty. All errors are swallowed and
    logged — filter mistakes must never break a sync.
    """
    if not html:
        return html
    rules = load_filter_rules()
    if rules.is_empty():
        return html
    scope = rules.for_account(account_name)
    if scope.is_empty():
        return html

    try:
        soup = BeautifulSoup(html, "html.parser")
        for sel in scope.remove_selectors:
            try:
                for el in soup.select(sel):
                    el.decompose()
            except Exception as exc:
                logger.warning("filter_rules: selector %r failed: %s", sel, exc)
        for elem_id in scope.remove_ids:
            for el in soup.find_all(id=elem_id):
                el.decompose()
        for cls in scope.remove_classes:
            for el in soup.find_all(class_=cls):
                el.decompose()
        out = str(soup)
    except Exception as exc:
        logger.warning("filter_rules: HTML parse failed, skipping selector/id/class rules: %s", exc)
        out = html

    for pattern in scope.remove_regex:
        try:
            out = re.sub(pattern, "", out, flags=re.DOTALL)
        except re.error as exc:
            logger.warning("filter_rules: regex %r invalid: %s", pattern, exc)
    return out


def reset_cache() -> None:
    """Clear the load cache. Intended for tests; callers in production rely on mtime invalidation."""
    _load_cached.cache_clear()
