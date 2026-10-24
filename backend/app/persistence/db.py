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


def make_engine(url: str) -> Engine:
    """
    Build an engine for a PostgreSQL URL with kestrel's connection setup.

    :param url: A ``postgresql+psycopg://`` SQLAlchemy URL.
    :returns: The new engine.
    """
    return create_engine(url, connect_args=_CONNECT_ARGS)


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
