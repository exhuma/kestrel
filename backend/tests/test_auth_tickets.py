"""Tests for short-lived, single-use SSE connection tickets."""
from __future__ import annotations

import time

import jwt
import pytest

from app.auth import tickets
from app.auth.identity import AuthenticatedUser


def _user(**overrides) -> AuthenticatedUser:
    base = {
        "sub": "user-1",
        "email": "user@example.com",
        "preferred_username": "user",
        "permissions": frozenset({"workflows:cleanup"}),
    }
    base.update(overrides)
    return AuthenticatedUser(**base)


def test_mint_then_validate_succeeds_once() -> None:
    """A freshly-minted ticket validates and carries the minted identity."""
    ticket = tickets.mint(_user())
    result = tickets.validate(ticket)
    assert result is not None
    assert result.sub == "user-1"
    assert result.permissions == frozenset({"workflows:cleanup"})


def test_reused_ticket_is_rejected() -> None:
    """A ticket is single-use: validating it twice fails the second time."""
    ticket = tickets.mint(_user())
    assert tickets.validate(ticket) is not None
    assert tickets.validate(ticket) is None


def test_expired_ticket_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ticket past its ~30s TTL is rejected."""
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() - 60)
    ticket = tickets.mint(_user())
    monkeypatch.setattr(time, "time", real_time)
    assert tickets.validate(ticket) is None


def test_tampered_ticket_is_rejected() -> None:
    """A ticket signed with a different secret fails signature verification."""
    forged = jwt.encode(
        {"sub": "attacker", "permissions": [], "exp": time.time() + 30,
         "jti": "forged"},
        "wrong-secret-that-is-long-enough-for-hs256",
        algorithm="HS256",
    )
    assert tickets.validate(forged) is None


def test_garbage_ticket_is_rejected() -> None:
    """A non-JWT string is rejected, not an unhandled exception."""
    assert tickets.validate("not-a-jwt-at-all") is None
