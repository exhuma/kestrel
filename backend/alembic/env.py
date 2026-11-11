"""Alembic environment wiring kestrel settings and metadata."""
from __future__ import annotations

from sqlalchemy import create_engine, pool

from alembic import context
from app.config import Settings
from app.persistence.board_tables import Base
from app.persistence.db import engine_url

config = context.config
# Respect a URL injected by tests/CLI; otherwise read settings
# fresh (no lru_cache) so stale caches cannot leak between runs. The
# configured URL stays out of the Alembic config: that is a ConfigParser,
# which rejects the "%" of a percent-encoded password.
database_url = engine_url(
    config.get_main_option("sqlalchemy.url") or Settings().database_url
)
# Imported from board_tables, which re-exports the shared ``Base``:
# loading that module registers the board tables on the same metadata.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = create_engine(database_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
