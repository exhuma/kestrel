"""Shared pytest configuration."""

from __future__ import annotations

import os

import pytest

from app.config import Settings, get_settings
from tests import database_support


def pytest_configure(config: pytest.Config) -> None:
    """Point the app's default database at a throw-away, migrated database.

    Code that falls back on the default database (an un-overridden store
    dependency, a cached ``get_sessionmaker()``) must never read or write a
    developer's database (constitution Principle III), and must find the
    same schema on a clean CI checkout as locally. The databases live on
    the PostgreSQL server ``KESTREL_TEST_DATABASE_URL`` names (see
    :mod:`tests.database_support`). Set before any test module is
    imported, so every cached engine binds to it; dropped again when the
    run ends, whatever its outcome.
    """
    if not os.environ.get(database_support.SERVER_URL_ENV):
        pytest.exit(
            f"{database_support.SERVER_URL_ENV} is not set: point it at a "
            "PostgreSQL server the tests may create databases on, e.g. "
            "postgresql+psycopg://postgres@127.0.0.1:5432/postgres",
            returncode=pytest.ExitCode.USAGE_ERROR,
        )
    config.add_cleanup(database_support.end_run)
    os.environ["KESTREL_DATABASE_URL"] = database_support.start_run()


@pytest.fixture(autouse=True)
def _drop_isolated_databases() -> None:
    """Drop the databases a test created with ``isolated_engine()``."""
    yield
    database_support.drop_isolated_databases()


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
