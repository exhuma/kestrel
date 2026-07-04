"""Shared pytest configuration."""
from __future__ import annotations

import pytest

from app.config import Settings, get_settings


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
