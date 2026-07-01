"""Database engine and session factory."""
from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """
    Return the process-wide database engine.

    :returns: The cached SQLAlchemy engine.
    """
    url = get_settings().database_url
    connect_args: dict[str, bool] = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(url, connect_args=connect_args)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    """
    Return the process-wide DB session factory.

    :returns: The cached sessionmaker bound to the engine.
    """
    return sessionmaker(bind=get_engine())
