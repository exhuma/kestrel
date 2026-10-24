"""Policy mapping board specialists to dispatch backends."""
from __future__ import annotations

from functools import lru_cache

from app.backends.base import Backend, Capability
from app.backends.registry import BackendRegistry, get_backend_registry
from app.config import get_settings
from app.models_board import SpecialistDefinition


class SpecialistCapabilityError(Exception):
    """A specialist was routed to a backend that cannot serve it."""

    def __init__(
        self,
        specialist_id: str,
        backend_id: str,
        missing: frozenset[Capability],
    ) -> None:
        names = ", ".join(sorted(c.value for c in missing))
        super().__init__(
            f"backend {backend_id!r} cannot serve specialist "
            f"{specialist_id!r}: missing capability {names}"
        )


class SpecialistBackendPolicy:
    """Resolves which backend runs a specialist (capability-checked).

    The board-domain counterpart to :class:`BackendPolicy`: instead of a
    fixed workflow step, this checks a :class:`SpecialistDefinition`'s
    declared ``required_abilities`` against the resolved backend's
    advertised capabilities (FR-007, FR-009).
    """

    def __init__(
        self, registry: BackendRegistry, default_backend: str
    ) -> None:
        self._registry = registry
        self._default = default_backend

    def backend_for(self, specialist: SpecialistDefinition) -> Backend:
        """
        Return the backend assigned to a specialist, capability-checked.

        :param specialist: The specialist to route.
        :returns: A backend whose capabilities satisfy the specialist.
        :raises SpecialistCapabilityError: If the chosen backend can't
            serve it.
        """
        backend_id = (
            self._default
            if specialist.model_policy == "default"
            else specialist.model_policy
        )
        backend = self._registry.get(backend_id)
        requirement = frozenset(
            Capability(a) for a in specialist.required_abilities
        )
        missing = requirement - backend.caps
        if missing:
            raise SpecialistCapabilityError(specialist.id, backend_id, missing)
        return backend


@lru_cache
def get_specialist_backend_policy() -> SpecialistBackendPolicy:
    """
    Return the process-wide SpecialistBackendPolicy singleton.

    :returns: The cached specialist backend policy instance.
    """
    settings = get_settings()
    return SpecialistBackendPolicy(
        get_backend_registry(), settings.default_session_backend
    )


