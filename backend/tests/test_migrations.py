"""Tests for the board-schema migration 0027 (feature 026)."""
from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

_BOARD_TABLES = [
    "board_workflow",
    "board_card",
    "board_card_relation",
    "board_card_attempt",
    "board_claim_lease",
    "board_workspace_lease",
    "board_artifact",
    "board_human_gate",
    "board_untrusted_input",
    "board_security_review",
    "board_coordinator_action",
    "board_event",
    "board_external_projection",
]

#: Fixed-driver / feedback-dispatch tables retired by migration 0028.
_RETIRED_TABLES = [
    "workflow_run",
    "workflow_step",
    "workflow_round_chip",
    "workflow_artifact",
    "review_request",
    "feedback_item",
    "feedback_cursor",
]


def _cfg(tmp_path: Path) -> tuple[Config, sa.Engine]:
    """Return an Alembic config and SQLite engine for a temporary database."""
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg, sa.create_engine(url)


def test_upgrade_creates_every_board_table(tmp_path: Path) -> None:
    """0027 adds every board-domain table alongside the fixed-driver ones."""
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "0026")
    command.upgrade(cfg, "0027")

    tables = set(sa.inspect(engine).get_table_names())
    assert set(_BOARD_TABLES) <= tables
    # The fixed-driver tables coexist untouched (feature 026 is additive
    # until the later clean-break phase removes them).
    assert "workflow_run" in tables
    assert "workflow_step" in tables


def test_downgrade_removes_every_board_table(tmp_path: Path) -> None:
    """Reversing 0027 drops every board table and nothing else."""
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "0027")
    command.downgrade(cfg, "0026")

    tables = set(sa.inspect(engine).get_table_names())
    assert not (set(_BOARD_TABLES) & tables)


def test_upgrade_to_head_drops_the_retired_fixed_driver_tables(
    tmp_path: Path,
) -> None:
    """0028 (Phase 10 clean break) drops the fixed-driver/feedback tables."""
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "head")

    tables = set(sa.inspect(engine).get_table_names())
    assert not (set(_RETIRED_TABLES) & tables)
    # The board schema and the tables it coexists with are unaffected.
    assert set(_BOARD_TABLES) <= tables
    assert "notification" in tables
    assert "child_task_link" in tables


def test_downgrade_from_head_restores_the_retired_tables(
    tmp_path: Path,
) -> None:
    """Reversing 0028 recreates every table it dropped."""
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0027")

    tables = set(sa.inspect(engine).get_table_names())
    assert set(_RETIRED_TABLES) <= tables
    assert "workflow_run" in tables


def test_board_workflow_source_task_ref_is_unique(tmp_path: Path) -> None:
    """The (source, task_ref) index rejects a duplicate insert."""
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "head")

    row = {
        "id": "wf-1",
        "source": "github-issue",
        "task_ref": "owner/repo#1",
        "repo": "owner/repo",
        "base_branch": "main",
        "source_visibility": "public",
        "title": "t",
        "state": "active",
        "revision": 1,
        "created_at": "2026-09-24T00:00:00",
    }
    with engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO board_workflow (id, source, task_ref, repo, "
            "base_branch, source_visibility, title, state, revision, "
            "created_at) VALUES (:id, :source, :task_ref, :repo, "
            ":base_branch, :source_visibility, :title, :state, :revision, "
            ":created_at)"
        ), row)

    duplicate = {**row, "id": "wf-2"}
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO board_workflow (id, source, task_ref, repo, "
            "base_branch, source_visibility, title, state, revision, "
            "created_at) VALUES (:id, :source, :task_ref, :repo, "
            ":base_branch, :source_visibility, :title, :state, :revision, "
            ":created_at)"
        ), duplicate)
