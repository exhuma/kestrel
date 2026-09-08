"""Tests for migration 0014 (retiring the "manual" run origin)."""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.persistence.workflow_store import WorkflowStore


def _cfg(tmp_path: Path) -> tuple[Config, sa.Engine]:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg, sa.create_engine(url)


def _seed(db: sa.Connection, run_id: str, source: str) -> None:
    db.execute(
        sa.text(
            "INSERT INTO workflow_run "
            "(id, repo, issue_number, issue_title, base_branch, branch, "
            " workspace, status, source, task_ref) VALUES "
            "(:id, 'o/r', 7, 't', 'main', 'b', 'w', 'done', :source, 'o/r#7')"
        ),
        {"id": run_id, "source": source},
    )


def test_upgrade_relabels_manual_runs_as_github(tmp_path: Path) -> None:
    """0014 relabels "manual" runs and leaves other sources untouched."""
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "0013")
    with engine.begin() as db:
        _seed(db, "wf-manual", "manual")
        _seed(db, "wf-jira", "jira-issue")

    command.upgrade(cfg, "0014")

    with engine.connect() as db:
        rows = dict(
            db.execute(sa.text("SELECT id, source FROM workflow_run")).all()
        )
    assert rows == {"wf-manual": "github-issue", "wf-jira": "jira-issue"}


def test_relabelled_run_loads_as_github_issue(tmp_path: Path) -> None:
    """A pre-0014 "manual" row loads back through the store as GitHub."""
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "0013")
    with engine.begin() as db:
        _seed(db, "wf-1", "manual")

    command.upgrade(cfg, "0014")
    # The relabelling itself is what this test verifies; upgrading the rest
    # of the way to head only keeps the schema in step with WorkflowRunRow's
    # current (post-0015) column set for the ORM load below.
    command.upgrade(cfg, "head")

    run = WorkflowStore(sessionmaker(bind=engine)).load_all()[0]
    assert run.source == "github-issue"
    assert run.task_ref == "o/r#7"


def test_new_rows_default_to_github_issue(tmp_path: Path) -> None:
    """After 0014 the column's server-default is "github-issue"."""
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "0014")
    with engine.begin() as db:
        db.execute(
            sa.text(
                "INSERT INTO workflow_run "
                "(id, repo, issue_number, issue_title, base_branch, branch, "
                " workspace, status, task_ref) VALUES "
                "('wf-1', 'o/r', 7, 't', 'main', 'b', 'w', 'done', 'o/r#7')"
            )
        )
    with engine.connect() as db:
        assert db.execute(
            sa.text("SELECT source FROM workflow_run WHERE id='wf-1'")
        ).scalar_one() == "github-issue"
