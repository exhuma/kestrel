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
        registry: BackendRegistry | None,
        step_backends: dict[str, str],
        default_backend: str,
    ) -> None:
        #: ``None`` for a label-only policy (see :func:`label_policy`), which
        #: exposes just :meth:`backend_id_for`; :meth:`backend_for` and
        #: :meth:`backends` require a real registry.
        self._registry = registry
        self._map = step_backends
        self._default = default_backend

    def backend_for(self, step: str) -> Backend:
        """
        Return the backend assigned to a step, verifying its capabilities.

        A dotted sub-step key (e.g. ``"refine.reconcile"``) resolves to
        its own backend when configured, otherwise falls back to the
        parent step (``"refine"``), then the default. Its capability
        requirement is inherited from the parent step.

        :param step: Workflow step name, e.g. ``"implement"`` or a
            dotted sub-step like ``"refine.reconcile"``.
        :returns: A backend whose capabilities satisfy the step.
        :raises BackendCapabilityError: If the chosen backend can't serve it.
        """
        parent = step.split(".", 1)[0]
        backend_id = self._map.get(step) or self._map.get(parent, self._default)
        backend = self._registry.get(backend_id)
        requirement = STEP_REQUIREMENTS.get(step) or STEP_REQUIREMENTS.get(
            parent, frozenset({Capability.TEXT})
        )
        missing = requirement - backend.caps
        if missing:
            raise BackendCapabilityError(step, backend_id, missing)
        return backend

    def backend_id_for(self, step: str) -> str:
        """
        Return the backend id assigned to a step, without validating it.

        The non-raising counterpart to :meth:`backend_for`: it resolves
        the same dotted-key fallback (own key -> parent step -> default)
        but performs no capability check and never touches the registry,
        so a read-only view (the workflow detail API) can label each
        step's backend even if that backend is misconfigured.

        :param step: Workflow step name or dotted sub-step key.
        :returns: The resolved backend id.
        """
        parent = step.split(".", 1)[0]
        return self._map.get(step) or self._map.get(parent, self._default)

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

        A dotted sub-step key (e.g. ``"refine.reconcile"``) uses its own
        override when set, otherwise falls back to the parent step's
        model (``"refine"``).

        :param step: Workflow step name, e.g. ``"plan"`` or a dotted
            sub-step like ``"refine.reconcile"``.
        :returns: Alias to pass to ``claude --model``.
        :raises KeyError: If the (parent) step is unknown.
        """
        if step in self._map:
            return self._map[step]
        return self._map[step.split(".", 1)[0]]


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

    Steps not listed in the backends file's ``step_backends`` fall back
    to its ``default_session_backend``.

    :returns: The cached backend policy instance.
    """
    settings = get_settings()
    return BackendPolicy(
        get_backend_registry(),
        settings.step_backends,
        settings.default_session_backend,
    )


def label_policy() -> BackendPolicy:
    """
    Return a registry-free policy for read-only step→backend labels.

    Only :meth:`BackendPolicy.backend_id_for` is valid on it. Because it never
    builds the backend registry, it never eagerly loads the session store from
    the database — so the read-only workflow detail API can label each step's
    backend without that side effect (and even if a backend is misconfigured).

    :returns: A settings-only policy (rebuilt each call; construction is cheap).
    """
    settings = get_settings()
    return BackendPolicy(
        None, settings.step_backends, settings.default_session_backend
    )
