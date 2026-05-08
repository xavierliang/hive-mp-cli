"""Runtime config. XDG-style data directory under ~/.hive-mp/, env override via HIVE_MP_HOME."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _data_home() -> Path:
    override = os.environ.get("HIVE_MP_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".hive-mp"


@dataclass(frozen=True)
class Paths:
    home: Path
    config_file: Path
    accounts_file: Path
    token_file: Path
    db_file: Path
    chrome_profile: Path
    articles_dir: Path
    logs_dir: Path
    filter_rules_file: Path

    @classmethod
    def resolve(cls) -> "Paths":
        home = _data_home()
        return cls(
            home=home,
            config_file=home / "config.json",
            accounts_file=home / "accounts.json",
            token_file=home / "token.json",
            db_file=home / "articles.db",
            chrome_profile=home / "chrome-profile",
            articles_dir=home / "articles",
            logs_dir=home / "logs",
            filter_rules_file=home / "filter_rules.yaml",
        )

    def ensure(self) -> None:
        for p in (self.home, self.chrome_profile, self.articles_dir, self.logs_dir):
            p.mkdir(parents=True, exist_ok=True)


PATHS = Paths.resolve()
