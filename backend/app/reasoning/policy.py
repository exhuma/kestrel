"""Which reasoning endpoint each role uses (``[reasoning]`` and its
``roles`` tables), with one concurrency limit per endpoint."""
from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from app.backends.limiter import BackendLimiter
from app.config import get_settings
from app.config_reasoning import ReasoningConfig
from app.models_board import SpecialistDefinition
from app.reasoning.client import ReasoningClient, ReasoningTarget


class ReasoningPolicy:
    """Hands out one :class:`ReasoningClient` per role."""

    def __init__(self, config: ReasoningConfig) -> None:
        self._config = config
        self._clients: dict[str, ReasoningClient] = {}
        self._limiters: dict[str, BackendLimiter] = {}

    def backend_for(self, specialist: SpecialistDefinition) -> ReasoningClient:
        """The client *specialist*'s reasoning turns run on."""
        return self.for_role(specialist.id)

    def for_role(self, role: str) -> ReasoningClient:
        """The client *role*'s reasoning turns run on."""
        if role not in self._clients:
            endpoint = self._config.for_role(role)
            limiter = self._limiters.setdefault(
                endpoint.base_url, BackendLimiter(endpoint.max_concurrency)
            )
            self._clients[role] = ReasoningClient(
                ReasoningTarget(role, endpoint), limiter
            )
        return self._clients[role]

    def timeout_for(self, role: str) -> float:
        """How long one of *role*'s reasoning turns may take."""
        return self._config.for_role(role).timeout_seconds

    def require_known_roles(self, known: Iterable[str]) -> None:
        """Refuse a ``[reasoning.roles.<role>]`` table for a role that
        does not exist, so a typo fails at startup.

        :raises ValueError: Naming each unknown role.
        """
        unknown = sorted(set(self._config.roles) - set(known))
        if unknown:
            raise ValueError(
                "[reasoning.roles] names unknown role(s): "
                + ", ".join(unknown)
            )

    def health_checks(self) -> list[tuple[str, ReasoningClient]]:
        """One client per distinct endpoint, labelled for the health view."""
        checks = [("reasoning", self.for_role(""))]
        seen = {self._config.for_role("").base_url}
        for role in sorted(self._config.roles):
            base_url = self._config.for_role(role).base_url
            if base_url not in seen:
                seen.add(base_url)
                checks.append((f"reasoning:{role}", self.for_role(role)))
        return checks


@lru_cache
def get_reasoning_policy() -> ReasoningPolicy:
    """The process-wide policy; settings validation guarantees the config.

    :raises ValueError: If ``[reasoning]`` is missing (only when settings
        were built without validation).
    """
    config = get_settings().reasoning
    if config is None:
        raise ValueError("[reasoning] is not configured")
    return ReasoningPolicy(config)
