"""Builds and resolves the configured agent backends."""
from __future__ import annotations

from functools import lru_cache

from app.backends.base import Backend, Capability
from app.backends.claude_cli import ClaudeCliBackend
from app.backends.openai_compat import OpenAICompatBackend
from app.backends.opencode import OpenCodeBackend
from app.config import BackendConfig, Settings, get_settings
from app.storage.registry import SessionRegistry, get_registry


class UnknownBackendError(KeyError):
    """Raised when a referenced backend id is not configured."""


class BackendRegistry:
    """Owns one :class:`Backend` instance per configured backend."""

    def __init__(
        self, settings: Settings, session_registry: SessionRegistry
    ) -> None:
        self._settings = settings
        self._session_registry = session_registry
        self._backends: dict[str, Backend] = {
            cfg.id: self._build(cfg) for cfg in settings.backends
        }
        # Fail fast on a misconfigured default rather than at first dispatch.
        self.default_session_backend()

    def _build(self, cfg: BackendConfig) -> Backend:
        backend: Backend
        if cfg.type == "claude_cli":
            backend = ClaudeCliBackend(
                self._settings, self._session_registry, backend_id=cfg.id
            )
        elif cfg.type == "openai_compat":
            backend = OpenAICompatBackend(
                self._settings, self._session_registry, cfg
            )
        elif cfg.type == "opencode":
            backend = OpenCodeBackend(
                self._settings, self._session_registry, cfg
            )
        else:
            raise NotImplementedError(
                f"backend type {cfg.type!r} is not implemented yet"
            )
        if cfg.caps is not None:
            backend.caps = frozenset(Capability(cap) for cap in cfg.caps)
        return backend

    def get(self, backend_id: str) -> Backend:
        """
        Return the backend with this id.

        :param backend_id: Configured backend id.
        :returns: The backend instance.
        :raises UnknownBackendError: If no such backend is configured.
        """
        try:
            return self._backends[backend_id]
        except KeyError:
            raise UnknownBackendError(backend_id) from None

    def default_session_backend(self) -> Backend:
        """Return the backend used for ad-hoc ``/api/sessions`` dispatch."""
        return self.get(self._settings.default_session_backend)

    def all(self) -> list[Backend]:
        """Return every configured backend."""
        return list(self._backends.values())


@lru_cache
def get_backend_registry() -> BackendRegistry:
    """Return the process-wide BackendRegistry singleton."""
    return BackendRegistry(get_settings(), get_registry())
