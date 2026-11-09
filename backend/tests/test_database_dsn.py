"""The configured database DSN does not name a Python driver."""
from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.pool import NullPool

from alembic import command
from app.persistence.db import engine_url, make_engine
from tests.database_support import empty_database

_DRIVER_URL = "postgresql+psycopg://user:pw@db:5432/kestrel?sslmode=require"
_ALEMBIC_INI = Path(__file__).parent.parent / "alembic.ini"


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://user:pw@db:5432/kestrel?sslmode=require",
        "postgres://user:pw@db:5432/kestrel?sslmode=require",
        _DRIVER_URL,
    ],
)
def test_a_postgresql_dsn_uses_the_psycopg_driver(dsn: str) -> None:
    """Ensure plain and driver-qualified DSNs end up as the same URL."""
    assert engine_url(dsn) == _DRIVER_URL


def test_only_the_scheme_is_rewritten() -> None:
    """Ensure a password that looks like a scheme stays as it is."""
    dsn = "postgresql://user:postgresql://x@db/kestrel"

    assert engine_url(dsn) == (
        "postgresql+psycopg://user:postgresql://x@db/kestrel"
    )


def test_another_scheme_is_left_alone() -> None:
    """Ensure a DSN for something else is not disguised as PostgreSQL."""
    assert engine_url("sqlite:///kestrel.db") == "sqlite:///kestrel.db"


def test_the_engine_accepts_a_plain_dsn() -> None:
    """Ensure the app's engine needs no driver in its DSN."""
    engine = make_engine("postgresql://user:pw@db/kestrel")

    assert engine.url.drivername == "postgresql+psycopg"


def test_migrations_accept_a_plain_dsn_with_percent_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure Alembic takes the configured DSN as an operator writes it.

    A percent-encoded value (a password with special characters, here a
    query parameter so the test needs no extra role) must reach the
    database unharmed.
    """
    database = empty_database()
    plain = database.replace("postgresql+psycopg://", "postgresql://", 1)
    monkeypatch.setenv(
        "KESTREL_DATABASE_URL", f"{plain}?application_name=kestrel%20migrate"
    )

    command.upgrade(Config(str(_ALEMBIC_INI)), "head")

    engine = sa.create_engine(database, poolclass=NullPool)
    with engine.connect() as conn:
        version = conn.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    engine.dispose()
    assert version == "0001"
