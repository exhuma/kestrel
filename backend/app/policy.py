"""Policy mapping workflow steps to models and to dispatch backends."""
from __future__ import annotations

from functools import lru_cache

from app.backends.base import Backend, Capability
from app.backends.registry import BackendRegistry, get_backend_registry
from app.config import get_settings

#: Default step -> model map (spec SRD 2.7). Opus is never on
#: the default path; enable it per step via
#: ``KESTREL_MODEL_OVERRIDES``.
DEFAULT_MODELS: dict[str, str] = {
    "gap_analysis": "haiku",
    "clarify": "haiku",
    "describe": "sonnet",
    "refine": "sonnet",
    "plan": "sonnet",
    "implement": "sonnet",
}

#: What each workflow step needs from its backend. Only ``implement``
#: mutates the working tree; the reasoning steps need text only, so a
#: plain LLM can serve them (it just won't read the repo). A backend
#: serves a step when its capabilities are a superset of the requirement.
STEP_REQUIREMENTS: dict[str, frozenset[Capability]] = {
    "gap_analysis": frozenset({Capability.TEXT}),
    "clarify": frozenset({Capability.TEXT}),
    "describe": frozenset({Capability.TEXT}),
    "refine": frozenset({Capability.TEXT}),
    "plan": frozenset({Capability.TEXT}),
    "implement": frozenset({Capability.TEXT, Capability.FILE_EDITS}),
}


class BackendCapabilityError(Exception):
    """A step was routed to a backend that cannot serve it."""

    def __init__(
        self, step: str, backend_id: str, missing: frozenset[Capability]
    ) -> None:
        names = ", ".join(sorted(c.value for c in missing))
        super().__init__(
            f"backend {backend_id!r} cannot serve step {step!r}: "
            f"missing capability {names}"
        )


class BackendPolicy:
    """Resolves which backend runs a workflow step (capability-checked)."""

    def __init__(
        self,
        registry: BackendRegistry,
        step_backends: dict[str, str],
        default_backend: str,
    ) -> None:
        self._registry = registry
        self._map = step_backends
        self._default = default_backend

    def backend_for(self, step: str) -> Backend:
        """
        Return the backend assigned to a step, verifying its capabilities.

        :param step: Workflow step name, e.g. ``"implement"``.
        :returns: A backend whose capabilities satisfy the step.
        :raises BackendCapabilityError: If the chosen backend can't serve it.
        """
        backend_id = self._map.get(step, self._default)
        backend = self._registry.get(backend_id)
        missing = STEP_REQUIREMENTS.get(
            step, frozenset({Capability.TEXT})
        ) - backend.caps
        if missing:
            raise BackendCapabilityError(step, backend_id, missing)
        return backend

    def backends(self) -> list[Backend]:
        """Every configured backend (used to stop a run's sessions)."""
        return self._registry.all()


class ModelPolicy:
    """Resolves which claude model a workflow step uses."""

    def __init__(self, overrides: dict[str, str]) -> None:
        self._map = {**DEFAULT_MODELS, **overrides}

    def model_for(self, step: str) -> str:
        """
        Return the model alias for a workflow step.

        :param step: Workflow step name, e.g. ``"plan"``.
        :returns: Alias to pass to ``claude --model``.
        :raises KeyError: If the step is unknown.
        """
        return self._map[step]


@lru_cache
def get_policy() -> ModelPolicy:
    """
    Return the process-wide ModelPolicy singleton.

    :returns: The cached model policy instance.
    """
    return ModelPolicy(get_settings().model_overrides)


@lru_cache
def get_backend_policy() -> BackendPolicy:
    """
    Return the process-wide BackendPolicy singleton.

    Steps not listed in ``KESTREL_STEP_BACKENDS`` fall back to
    ``KESTREL_DEFAULT_SESSION_BACKEND``.

    :returns: The cached backend policy instance.
    """
    settings = get_settings()
    return BackendPolicy(
        get_backend_registry(),
        settings.step_backends,
        settings.default_session_backend,
    )
