"""Tests for child-task link persistence and migration 0018."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.persistence.child_task_store import ChildTaskStore
from app.persistence.tables import ChildTaskLinkRow


def _cfg(tmp_path: Path) -> tuple[Config, sa.Engine]:
    """Return an Alembic config and SQLite engine for a temporary database."""
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg, sa.create_engine(url)


def _factory(tmp_path: Path) -> sessionmaker[sa.orm.Session]:
    """Upgrade a temporary database and return its session factory."""
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "head")
    return sessionmaker(bind=engine)


def test_upgrade_creates_child_task_link_table(tmp_path: Path) -> None:
    """0018 adds every durable child-link and lifecycle column."""
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "0017")
    command.upgrade(cfg, "0018")

    columns = {
        column["name"]
        for column in sa.inspect(engine).get_columns("child_task_link")
    }
    assert columns == {
        "task_ref",
        "parent_workflow_id",
        "latest_workflow_id",
        "source_state",
        "source_generation",
        "closed_at",
        "retired_at",
    }


def test_upgrade_adds_child_task_dag_columns(tmp_path: Path) -> None:
    """0023 adds the durable identities and parent integration branch."""
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "0022")
    command.upgrade(cfg, "0023")

    columns = {
        column["name"]
        for column in sa.inspect(engine).get_columns("child_task_link")
    }
    assert {"task_node_id", "prerequisites", "integration_branch"} <= columns


def test_store_reads_dag_metadata_and_ready_node_ids(tmp_path: Path) -> None:
    """A linked child keeps its DAG metadata through its ready run head."""
    store = ChildTaskStore(_factory(tmp_path))
    store.record("parent", "o/r#8", "TASK-2", ("TASK-1",), "kestrel/issue-1")
    store.record_run("o/r#8", "wf-2")

    schedule = store.scheduling_details("o/r#8")
    assert schedule is not None
    assert schedule.prerequisites == ("TASK-1",)
    assert store.ready_task_node_ids({"wf-2"}) == {"TASK-2"}


def test_reopen_claim_updates_the_run_head(tmp_path: Path) -> None:
    """Only a closed child's latest run can claim its one successor."""
    factory = _factory(tmp_path)
    store = ChildTaskStore(factory)
    store.record("parent", "o/r#8")
    store.record_run("o/r#8", "wf-1")
    store.observe_source_state("o/r#8", "closed")

    assert store.claim_reopen("o/r#8", "wrong") is False
    assert store.claim_reopen("o/r#8", "wf-1") is True
    assert store.claim_reopen("o/r#8", "wf-1") is False
    store.complete_reopen("o/r#8", "wf-2")

    with factory() as db:
        row = db.get(ChildTaskLinkRow, "o/r#8")
        assert row.latest_workflow_id == "wf-2"
        assert row.source_state == "open"
        assert row.closed_at is None


def test_generation_change_creates_one_reopen_edge(tmp_path: Path) -> None:
    """A local task generation change closes a child only after its baseline."""
    store = ChildTaskStore(_factory(tmp_path))
    store.record("parent", "local:child")

    assert store.observe_generation("local:child", "1") is False
    assert store.observe_generation("local:child", "2") is True

    with _factory(tmp_path)() as db:
        row = db.get(ChildTaskLinkRow, "local:child")
        assert row.source_state == "closed"


def test_closed_child_retention_claim_is_one_time(tmp_path: Path) -> None:
    """A first closure remains the retirement baseline and claims once."""
    factory = _factory(tmp_path)
    store = ChildTaskStore(factory)
    store.record("parent", "o/r#8")
    store.record_run("o/r#8", "wf-1")
    store.observe_source_state("o/r#8", "closed")
    with factory() as db:
        row = db.get(ChildTaskLinkRow, "o/r#8")
        closed_at = row.closed_at

    store.observe_source_state("o/r#8", "closed")
    assert store.retirement_candidates(closed_at + timedelta(seconds=1)) == [
        ("o/r#8", "wf-1")
    ]
    assert store.claim_retirement("o/r#8") is True
    assert store.claim_retirement("o/r#8") is False
    assert store.mark_retired("o/r#8", datetime.now(timezone.utc)) is True
    assert store.is_retired("o/r#8") is True
    assert store.retirement_candidates(datetime.now(timezone.utc)) == []
