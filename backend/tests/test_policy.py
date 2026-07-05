"""Tests for the model-selection policy."""
from __future__ import annotations

import pytest

from app.policy import DEFAULT_MODELS, ModelPolicy


def test_defaults_have_no_opus() -> None:
    """Ensure the default policy never selects opus."""
    assert "opus" not in DEFAULT_MODELS.values()


def test_model_for_uses_defaults() -> None:
    """Ensure known steps resolve to their default model."""
    policy = ModelPolicy(overrides={})
    assert policy.model_for("gap_analysis") == "haiku"
    assert policy.model_for("implement") == "sonnet"


def test_overrides_win() -> None:
    """Ensure configured overrides replace defaults."""
    policy = ModelPolicy(overrides={"plan": "opus"})
    assert policy.model_for("plan") == "opus"


def test_unknown_step_raises() -> None:
    """Ensure unknown steps fail loudly."""
    policy = ModelPolicy(overrides={})
    with pytest.raises(KeyError):
        policy.model_for("nonsense")


def test_refine_step_has_a_default_model() -> None:
    """Ensure the workflow's refine step is in the policy."""
    assert ModelPolicy(overrides={}).model_for("refine") == (
        "sonnet"
    )


def test_substep_falls_back_to_parent_model() -> None:
    """Ensure a dotted sub-step inherits the parent step's model."""
    assert ModelPolicy(overrides={}).model_for("refine.reconcile") == (
        "sonnet"
    )


def test_substep_override_beats_parent() -> None:
    """Ensure a sub-step override applies only to that sub-step."""
    policy = ModelPolicy(overrides={"refine.reconcile": "opus"})
    assert policy.model_for("refine.reconcile") == "opus"
    assert policy.model_for("refine.generate") == "sonnet"  # parent
    assert policy.model_for("refine") == "sonnet"


def test_substep_of_unknown_parent_raises() -> None:
    """Ensure a sub-step of an unknown step still fails loudly."""
    with pytest.raises(KeyError):
        ModelPolicy(overrides={}).model_for("nonsense.sub")
