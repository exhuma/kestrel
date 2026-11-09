"""Database engine and session factory."""
from __future__ import annotations

from functools import lru_cache

from psycopg import errors
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

#: libpq options for every connection. The ``DateTime`` columns hold naive
#: UTC; a UTC session time zone keeps a timezone-aware value written to
#: them (or compared with them) in UTC whatever the server's own setting.
_CONNECT_ARGS = {"options": "-c timezone=UTC"}

#: The URL schemes of a standard PostgreSQL DSN.
_PLAIN_SCHEMES = ("postgresql", "postgres")


def engine_url(dsn: str) -> str:
    """
    Turn a standard PostgreSQL DSN into the URL SQLAlchemy needs.

    The driver is an internal detail, so the configured DSN does not name
    it; SQLAlchemy would otherwise load its default driver, psycopg2.

    :param dsn: The configured DSN (``postgresql://user:pw@host/db``).
    :returns: The DSN naming kestrel's driver. A DSN that already names a
        driver, or has another scheme, is returned unchanged.
    """
    scheme, separator, rest = dsn.partition("://")
    if separator and scheme in _PLAIN_SCHEMES:
        return f"postgresql+psycopg://{rest}"
    return dsn


def make_engine(url: str) -> Engine:
    """
    Build an engine for a PostgreSQL URL with kestrel's connection setup.

    :param url: The database's DSN.
    :returns: The new engine.
    """
    return create_engine(engine_url(url), connect_args=_CONNECT_ARGS)


def is_unique_violation(error: IntegrityError) -> bool:
    """
    Tell a duplicate key from any other integrity failure.

    :param error: The error a write raised.
    :returns: ``True`` when a unique key rejected the write; ``False`` for
        anything else, such as a dangling foreign key.
    """
    return isinstance(error.orig, errors.UniqueViolation)


@lru_cache
def get_engine() -> Engine:
    """
    Return the process-wide database engine.

    :returns: The cached SQLAlchemy engine.
    """
    return make_engine(get_settings().database_url)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    """
    Return the process-wide DB session factory.

    :returns: The cached sessionmaker bound to the engine.
    """
    return sessionmaker(bind=get_engine())
