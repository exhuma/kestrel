"""Tests for the Alembic baseline migration."""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.pool import NullPool

from alembic import command
from app.persistence.board_tables import Base
from tests.database_support import alembic_config, empty_database


@pytest.fixture(name="database")
def _database() -> str:
    """An empty database (not cloned from the migrated template)."""
    return empty_database()


def _tables(url: str) -> set[str]:
    engine = sa.create_engine(url, poolclass=NullPool)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_every_model_table(database: str) -> None:
    """Ensure ``upgrade head`` creates every table the models declare."""
    command.upgrade(alembic_config(database), "head")

    assert set(Base.metadata.tables) <= _tables(database)


def test_migrated_schema_matches_the_models(database: str) -> None:
    """Ensure autogenerate finds no difference between schema and models."""
    command.upgrade(alembic_config(database), "head")

    engine = sa.create_engine(database, poolclass=NullPool)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []


def test_downgrade_to_base_drops_every_table(database: str) -> None:
    """Ensure ``downgrade base`` leaves only Alembic's own table."""
    config = alembic_config(database)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    assert _tables(database) == {"alembic_version"}


def test_workflow_source_task_ref_is_unique(database: str) -> None:
    """Ensure the ``(source, task_ref)`` index rejects a duplicate."""
    command.upgrade(alembic_config(database), "head")
    insert = sa.text(
        "INSERT INTO board_workflow (id, source, task_ref, repo, "
        "base_branch, source_visibility, title, state, created_at) "
        "VALUES (:id, 'github-issue', 'o/r#1', 'o/r', 'main', 'public', "
        "'t', 'active', now())"
    )
    engine = sa.create_engine(database, poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(insert, {"id": "wf-1"})

    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        conn.execute(insert, {"id": "wf-2"})
    engine.dispose()


def test_foreign_keys_are_enforced(database: str) -> None:
    """Ensure a card cannot reference a workflow that does not exist."""
    command.upgrade(alembic_config(database), "head")
    engine = sa.create_engine(database, poolclass=NullPool)

    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO board_card (id, workflow_id, kind, title, state, "
            "eligible_roles, acceptance_contract, created_at, updated_at) "
            "VALUES ('c-1', 'missing', 'analysis', 't', 'ready', '', '{}', "
            "now(), now())"
        ))
    engine.dispose()
