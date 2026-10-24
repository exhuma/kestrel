"""Shared pytest configuration."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from app.config import Settings, get_settings


def pytest_configure(config: pytest.Config) -> None:
    """Point the app's default database at a fresh, migrated temporary file.

    Code that falls back on the default database (an un-overridden store
    dependency, a cached ``get_sessionmaker()``) must never read or write a
    developer's ``kestrel.db`` (constitution Principle III), and must find
    the same schema on a clean CI checkout as locally. Set before any test
    module is imported, so every cached engine binds to it; removed again
    when the run ends.
    """
    directory = tempfile.mkdtemp(prefix="kestrel-tests-")
    config.add_cleanup(lambda: shutil.rmtree(directory, ignore_errors=True))
    database = Path(directory) / "kestrel.db"
    url = f"sqlite:///{database}"
    os.environ["KESTREL_DATABASE_URL"] = url
    alembic_config = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    alembic_config.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_config, "head")


@pytest.fixture(autouse=True)
def _ignore_developer_dotenv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep tests hermetic: never read a developer's ``backend/.env``.

    Without this, any ``Settings()`` built in a test would load the local
    ``.env`` (e.g. one pointing the default session backend at a custom
    LLM), silently changing test behavior. Tests that need specific config
    still pass it explicitly.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
