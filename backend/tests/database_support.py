"""Throw-away PostgreSQL databases for the test suite.

``KESTREL_TEST_DATABASE_URL`` names a PostgreSQL server (any database on
it; the user must be allowed to create databases). Each run migrates one
template database, then clones it: once for the shared database the app's
default engine uses, and once more for every test that asks for an
isolated database (:func:`isolated_engine`); :func:`empty_database`
gives an unmigrated one. Cloning a template is much faster than
migrating, and every name carries a per-run prefix, so runs sharing a
server never collide. Everything the run created is dropped again.
"""
from __future__ import annotations

import itertools
import os
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.pool import NullPool

from alembic import command
from app.persistence.db import make_engine

#: The environment variable naming the PostgreSQL server for tests.
SERVER_URL_ENV = "KESTREL_TEST_DATABASE_URL"

_PREFIX = f"kestrel_test_{uuid.uuid4().hex[:8]}"
_TEMPLATE = f"{_PREFIX}_template"
_SHARED = f"{_PREFIX}_shared"
_ALEMBIC_INI = Path(__file__).parent.parent / "alembic.ini"
_numbers = itertools.count()
#: Isolated databases created during the current test, dropped after it,
#: with the engine (if any) to dispose of first.
_isolated: list[tuple[str, sa.Engine | None]] = []
_by_key: dict[Path, sa.Engine] = {}


def database_url(name: str) -> str:
    """
    The URL of database *name* on the test server.

    :param name: A database name.
    :returns: A SQLAlchemy URL, password included.
    """
    server = sa.make_url(os.environ[SERVER_URL_ENV])
    return server.set(database=name).render_as_string(hide_password=False)


def _admin(statement: str) -> None:
    """Run one ``CREATE``/``DROP DATABASE`` statement on the server."""
    engine = sa.create_engine(
        os.environ[SERVER_URL_ENV],
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    with engine.connect() as conn:
        conn.execute(sa.text(statement))
    engine.dispose()


def create_database(name: str, template: str | None = None) -> str:
    """
    Create database *name*, empty or as a copy of *template*.

    :param name: The new database's name.
    :param template: The database to copy, if any.
    :returns: The new database's URL.
    """
    copy = f' TEMPLATE "{template}"' if template else ""
    _admin(f'CREATE DATABASE "{name}"{copy}')
    return database_url(name)


def drop_database(name: str) -> None:
    """
    Drop database *name* if it exists, closing any open connection to it.

    :param name: The database's name.
    """
    _admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def alembic_config(url: str) -> Config:
    """
    An Alembic configuration pointed at *url*.

    :param url: The database to migrate.
    :returns: The configuration.
    """
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)
    return config


def start_run() -> str:
    """
    Migrate the run's template and create the shared database from it.

    :returns: The shared database's URL.
    """
    command.upgrade(alembic_config(create_database(_TEMPLATE)), "head")
    return create_database(_SHARED, template=_TEMPLATE)


def end_run() -> None:
    """Drop every database this run created; safe after a partial start."""
    drop_isolated_databases()
    drop_database(_SHARED)
    drop_database(_TEMPLATE)


def empty_database() -> str:
    """
    A fresh, empty database, dropped when the current test ends.

    :returns: The database's URL.
    """
    name = f"{_PREFIX}_{next(_numbers)}"
    _isolated.append((name, None))
    return create_database(name)


def isolated_engine(key: Path | None = None) -> sa.Engine:
    """
    An engine on a fresh, migrated database of its own.

    The engine is disposed of and the database dropped when the current
    test ends.

    :param key: Calls with the same key during one test share a database
        (a test's ``tmp_path``, say).
    :returns: The engine.
    """
    if key is not None and key in _by_key:
        return _by_key[key]
    name = f"{_PREFIX}_{next(_numbers)}"
    engine = make_engine(create_database(name, template=_TEMPLATE))
    _isolated.append((name, engine))
    if key is not None:
        _by_key[key] = engine
    return engine


def drop_isolated_databases() -> None:
    """Drop the databases the current test created."""
    _by_key.clear()
    while _isolated:
        name, engine = _isolated.pop()
        if engine is not None:
            engine.dispose()
        drop_database(name)
