"""Tests for migration 0007 (Jira source-neutral task_ref identity)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command


def _cfg(tmp_path: Path) -> tuple[Config, sa.Engine]:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg, sa.create_engine(url)


def test_upgrade_backfills_task_ref_and_dismissal_key(
    tmp_path: Path,
) -> None:
    """0007 backfills workflow_run.task_ref and re-keys issue_dismissal."""
    cfg, engine = _cfg(tmp_path)
    # Build the pre-0007 schema and seed a GitHub run + dismissal.
    command.upgrade(cfg, "0006")
    now = datetime.now(timezone.utc)
    with engine.begin() as db:
        db.execute(
            sa.text(
                "INSERT INTO workflow_run "
                "(id, repo, issue_number, issue_title, base_branch, branch, "
                " workspace, status, source) VALUES "
                "('wf-1', 'o/r', 7, 't', 'main', 'b', 'w', 'done', "
                "'github-issue')"
            )
        )
        db.execute(
            sa.text(
                "INSERT INTO issue_dismissal (repo, issue_number, created_at) "
                "VALUES ('o/r', 9, :ts)"
            ),
            {"ts": now},
        )

    command.upgrade(cfg, "0007")

    with engine.connect() as db:
        assert db.execute(
            sa.text("SELECT task_ref FROM workflow_run WHERE id='wf-1'")
        ).scalar_one() == "o/r#7"
        assert db.execute(
            sa.text("SELECT task_ref FROM issue_dismissal")
        ).scalar_one() == "o/r#9"
        cols = {
            c["name"]
            for c in sa.inspect(engine).get_columns("issue_dismissal")
        }
        assert cols == {"task_ref", "created_at"}
        issue_col = next(
            c for c in sa.inspect(engine).get_columns("workflow_run")
            if c["name"] == "issue_number"
        )
        assert issue_col["nullable"] is True


def test_downgrade_restores_prior_shape(tmp_path: Path) -> None:
    """Downgrading 0007 restores the (repo, issue_number) dismissal shape."""
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "0007")
    now = datetime.now(timezone.utc)
    with engine.begin() as db:
        db.execute(
            sa.text(
                "INSERT INTO issue_dismissal (task_ref, created_at) "
                "VALUES ('o/r#9', :ts)"
            ),
            {"ts": now},
        )

    command.downgrade(cfg, "0006")

    cols = {
        c["name"]
        for c in sa.inspect(engine).get_columns("issue_dismissal")
    }
    assert cols == {"repo", "issue_number", "created_at"}
    with engine.connect() as db:
        row = db.execute(
            sa.text("SELECT repo, issue_number FROM issue_dismissal")
        ).one()
        assert (row.repo, row.issue_number) == ("o/r", 9)
    wf_cols = {
        c["name"]
        for c in sa.inspect(engine).get_columns("workflow_run")
    }
    assert "task_ref" not in wf_cols
