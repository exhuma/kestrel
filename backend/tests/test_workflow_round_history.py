"""Tests for the persisted workflow round-chip history trail.

Covers the store round-trip, the WorkflowRegistry passthrough, and the
WorkflowService choke points (_retire_sessions/_show_sessions) that
freeze a step's live chips into durable history — see AGENTS.md's
"chip history" work: StepSession stays ephemeral, RoundChip is the
durable afterimage written once a step's chips are retired.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.models_workflow import (
    StepSession,
    WorkflowRun,
    WorkflowStep,
)
from app.persistence.workflow_store import WorkflowStore
from app.services.workflows import WorkflowService
from app.services.workflows.driver.escalate import fail_active_steps
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry
from tests.conftest import (
    _FakeDismissals,
    _FakeGit,
    _FakeGitHub,
    _FakeNotifier,
    _FakeRunner,
    _settings,
)


def _migrate(db_path: Path) -> str:
    """Apply all migrations to a fresh SQLite file."""
    url = f"sqlite:///{db_path}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


def _store(tmp_path: Path) -> WorkflowStore:
    url = _migrate(tmp_path / "wf.db")
    factory = sessionmaker(bind=sa.create_engine(url))
    return WorkflowStore(factory)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- store round-trip ------------------------------------------------


def test_save_round_chips_is_a_noop_on_empty_list(tmp_path: Path) -> None:
    """Ensure retiring an empty chip set writes nothing."""
    store = _store(tmp_path)
    store.save_round_chips("wf-1", "design", [], _now())
    assert store.load_round_chips("wf-1") == []


def test_save_and_load_round_chips_round_trip(tmp_path: Path) -> None:
    """Ensure a frozen chip group survives a save/load cycle intact."""
    store = _store(tmp_path)
    chip = StepSession(
        profile_id="designer", label="Designer", badge="agent",
        session_id="s1", status="idle",
    )
    store.save_round_chips("wf-1", "design", [chip], _now())

    history = store.load_round_chips("wf-1")

    assert len(history) == 1
    loaded = history[0]
    assert loaded.step == "design"
    assert loaded.round_index == 0
    assert loaded.profile_id == "designer"
    assert loaded.label == "Designer"
    assert loaded.badge == "agent"
    assert loaded.session_id == "s1"
    assert loaded.status == "idle"


def test_save_round_chips_freezes_a_running_chip_as_error(
    tmp_path: Path,
) -> None:
    """A chip still "running" when frozen is terminal history now."""
    store = _store(tmp_path)
    chip = StepSession(profile_id="coder", label="Coder", status="running")
    store.save_round_chips("wf-1", "code", [chip], _now())
    assert store.load_round_chips("wf-1")[0].status == "error"


def test_round_index_increments_per_step_across_calls(
    tmp_path: Path,
) -> None:
    """Ensure successive retires of the same step form separate rounds."""
    store = _store(tmp_path)
    store.save_round_chips(
        "wf-1", "refine",
        [StepSession(profile_id="coordinator", label="Coordinator")],
        _now(),
    )
    store.save_round_chips(
        "wf-1", "refine",
        [StepSession(profile_id="writer", label="Writer")],
        _now(),
    )

    history = store.load_round_chips("wf-1")

    assert [c.round_index for c in history] == [0, 1]


def test_load_round_chips_orders_by_step_then_round(tmp_path: Path) -> None:
    """Ensure history groups by step name, then round, for stable display."""
    store = _store(tmp_path)
    store.save_round_chips(
        "wf-1", "code", [StepSession(profile_id="coder", label="Coder")],
        _now(),
    )
    store.save_round_chips(
        "wf-1", "design",
        [StepSession(profile_id="designer", label="Designer")], _now(),
    )

    history = store.load_round_chips("wf-1")

    assert [c.step for c in history] == ["code", "design"]


def test_delete_purges_round_chip_rows(tmp_path: Path) -> None:
    """Ensure deleting a run cascades to its round-chip history."""
    store = _store(tmp_path)
    store.save_round_chips(
        "wf-1", "design",
        [StepSession(profile_id="designer", label="Designer")], _now(),
    )
    store.delete("wf-1")
    assert store.load_round_chips("wf-1") == []


# ---- registry passthrough ---------------------------------------------


def test_registry_without_store_no_ops_and_returns_empty() -> None:
    """Ensure an in-memory-only registry (unit tests) never errors."""
    reg = WorkflowRegistry()
    reg.save_round_chips(
        "wf-1", "design",
        [StepSession(profile_id="designer", label="Designer")], _now(),
    )
    assert reg.load_round_chips("wf-1") == []


def test_registry_with_store_delegates(tmp_path: Path) -> None:
    """Ensure a store-backed registry writes through and reads back."""
    reg = WorkflowRegistry(store=_store(tmp_path))
    reg.save_round_chips(
        "wf-1", "design",
        [StepSession(profile_id="designer", label="Designer")], _now(),
    )
    assert len(reg.load_round_chips("wf-1")) == 1


# ---- service choke points ----------------------------------------------


def _service_with_store(tmp_path: Path) -> tuple[WorkflowService, WorkflowRun]:
    runner = _FakeRunner(SessionRegistry(), outputs=[])
    reg = WorkflowRegistry(store=_store(tmp_path))
    svc = WorkflowService(
        settings=_settings(),
        sessions=runner.sessions,
        workflows=reg,
        backends=runner,
        git=_FakeGit(),
        github=_FakeGitHub(),
        notifier=_FakeNotifier(),
        dismissals=_FakeDismissals(),
    )
    run = WorkflowRun(
        id="wf-1", repo="o/r", issue_number=1,
        steps=[WorkflowStep(name="design"), WorkflowStep(name="code")],
    )
    reg.create(run)
    return svc, run


def test_retire_sessions_freezes_then_clears(tmp_path: Path) -> None:
    """Ensure retiring a step's chips persists them, then clears the live
    set — the single choke point every "chips off" call site uses."""
    svc, run = _service_with_store(tmp_path)
    step = run.steps[0]
    step.active_sessions = [
        StepSession(profile_id="designer", label="Designer", status="idle")
    ]

    svc._retire_sessions(run, step)

    assert step.active_sessions == []
    assert len(svc.round_history(run.id)) == 1


def test_retire_sessions_is_a_noop_when_nothing_live(tmp_path: Path) -> None:
    """Ensure retiring an already-empty step writes no history."""
    svc, run = _service_with_store(tmp_path)
    svc._retire_sessions(run, run.steps[0])
    assert svc.round_history(run.id) == []


def test_show_sessions_freezes_the_outgoing_set_first(tmp_path: Path) -> None:
    """Ensure two successive _show_sessions calls (e.g. coordinator then
    writer) each become their own history group, not silently dropped."""
    svc, run = _service_with_store(tmp_path)

    svc._show_sessions(
        run, [StepSession(profile_id="coordinator", label="Coordinator")]
    )
    svc._show_sessions(
        run, [StepSession(profile_id="writer", label="Writer")]
    )

    history = svc.round_history(run.id)
    assert [c.profile_id for c in history] == ["coordinator"]
    assert run.steps[0].active_sessions[0].profile_id == "writer"


def test_fail_active_steps_retires_a_stranded_running_chip(
    tmp_path: Path,
) -> None:
    """Ensure escalation freezes a still-running chip into history as an
    error, instead of silently discarding it."""
    svc, run = _service_with_store(tmp_path)
    step = run.steps[0]
    step.status = "running"
    step.active_sessions = [
        StepSession(profile_id="designer", label="Designer", status="running")
    ]

    fail_active_steps(svc, run)

    assert step.status == "failed"
    assert step.active_sessions == []
    history = svc.round_history(run.id)
    assert len(history) == 1
    assert history[0].status == "error"
