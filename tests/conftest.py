from __future__ import annotations

from pathlib import Path

import pytest

from hive_mp_cli import config as cfg_module
from hive_mp_cli.auth import token as token_store
from hive_mp_cli.storage import accounts as accounts_store


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ~/.hive-mp/ to a tmp path for the test's lifetime."""
    monkeypatch.setenv("HIVE_MP_HOME", str(tmp_path))
    new_paths = cfg_module.Paths.resolve()
    monkeypatch.setattr(cfg_module, "PATHS", new_paths)
    monkeypatch.setattr(token_store, "PATHS", new_paths)
    monkeypatch.setattr(accounts_store, "PATHS", new_paths)

    # Storage modules cache PATHS at import time; patch their references too.
    from hive_mp_cli.storage import db as db_store
    from hive_mp_cli.storage import files as files_store  # noqa: F401
    monkeypatch.setattr(db_store, "PATHS", new_paths)

    from hive_mp_cli.commands import article as article_cmd
    from hive_mp_cli.commands import sync as sync_cmd
    monkeypatch.setattr(article_cmd, "PATHS", new_paths)
    monkeypatch.setattr(sync_cmd, "PATHS", new_paths)

    return tmp_path
