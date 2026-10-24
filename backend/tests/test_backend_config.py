"""Tests for per-backend concurrency and rate-limit configuration."""
from __future__ import annotations

import pytest

from app.config_models import BackendConfig

_DEFAULT_CONCURRENCY = 1
_DEFAULT_RETRIES = 3
_DEFAULT_BACKOFF_SECONDS = 2.0


def test_backend_concurrency_and_backoff_defaults() -> None:
    """Ensure backend throttling settings default to conservative values."""
    config = BackendConfig(id="x")
    assert config.max_concurrency == _DEFAULT_CONCURRENCY
    assert config.rate_limit_retries == _DEFAULT_RETRIES
    assert config.rate_limit_backoff_seconds == _DEFAULT_BACKOFF_SECONDS


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_concurrency", 0),
        ("rate_limit_retries", -1),
        ("rate_limit_backoff_seconds", 0),
    ],
)
def test_backend_concurrency_and_backoff_reject_invalid_values(
    field: str, value: int
) -> None:
    """Ensure invalid backend throttling settings fail validation by field."""
    with pytest.raises(ValueError, match=field):
        BackendConfig(id="x", **{field: value})


def test_backend_config_rejects_unexpected_fields() -> None:
    """Ensure a stray key (e.g. a misplaced default_session_backend after
    a [[backends]] header) fails loudly instead of being ignored."""
    with pytest.raises(ValueError, match="default_session_backend"):
        BackendConfig(id="x", default_session_backend="oc")
