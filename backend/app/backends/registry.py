"""Builds and resolves the configured agent backends."""
from __future__ import annotations

from functools import lru_cache

from app.backends.base import Backend, Capability
from app.backends.claude_cli import ClaudeCliBackend
from app.backends.limiter import BackendLimiter
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
        limiter = BackendLimiter(cfg.max_concurrency)
        if cfg.type == "claude_cli":
            backend = ClaudeCliBackend(
                self._settings,
                self._session_registry,
                backend_id=cfg.id,
                limiter=limiter,
            )
        elif cfg.type == "openai_compat":
            backend = OpenAICompatBackend(
                self._settings, self._session_registry, cfg, limiter=limiter
            )
        elif cfg.type == "opencode":
            backend = OpenCodeBackend(
                self._settings, self._session_registry, cfg, limiter=limiter
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
            raise UnknownBackendError(
                f"{backend_id!r} (configured backend ids: "
                f"{sorted(self._backends)})"
            ) from None

    def default_session_backend(self) -> Backend:
        """Return the backend used for ad-hoc ``/api/sessions`` dispatch.

        :raises UnknownBackendError: If ``default_session_backend`` names
            no configured backend — commonly a TOML ordering mistake: a
            bare key placed after a ``[[backends]]`` header parses as a
            field of that table, not a top-level setting (rejected loudly
            by ``BackendConfig``'s ``extra="forbid"``), or the key was
            simply never changed from its ``"claude"`` default.
        """
        try:
            return self.get(self._settings.default_session_backend)
        except UnknownBackendError:
            configured = sorted(self._backends)
            raise UnknownBackendError(
                f"default_session_backend="
                f"{self._settings.default_session_backend!r} has no "
                f"matching `backends` entry (configured ids: "
                f"{configured}). Check config.toml: "
                "`default_session_backend` must be set before any "
                "[[backends]] table — a bare key placed after an "
                "array-of-tables header becomes part of that table, "
                "not a top-level setting."
            ) from None

    def all(self) -> list[Backend]:
        """Return every configured backend."""
        return list(self._backends.values())


@lru_cache
def get_backend_registry() -> BackendRegistry:
    """Return the process-wide BackendRegistry singleton."""
    return BackendRegistry(get_settings(), get_registry())
