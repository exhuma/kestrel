"""Config for kestrel's internal reasoning: the OpenAI-compatible chat
endpoint kestrel uses for its own thinking, apart from the agent backends.

A turn that works in a checked-out repository runs on an agent backend
(``[[backends]]``); every other turn (screening, reading a reply,
coordinating, drafting the understanding or the PRD) runs here. The
``[reasoning]`` table is required; ``[reasoning.roles.<role>]`` tables
change any of its fields for one specialist role. Keys stay in the
environment: each endpoint names the variable that holds its key.
"""
from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field

#: The variable holding the reasoning key when ``api_key_env`` is unset.
DEFAULT_KEY_ENV = "KESTREL_REASONING_API_KEY"


class ReasoningEndpoint(BaseModel):
    """One endpoint and model, complete."""

    model_config = ConfigDict(extra="forbid")

    #: The OpenAI-compatible API root, e.g. ``https://host/v1``; kestrel
    #: posts to ``<base_url>/chat/completions``.
    base_url: str = ""
    model: str = ""
    #: The environment variable holding this endpoint's API key.
    api_key_env: str = DEFAULT_KEY_ENV
    timeout_seconds: float = Field(default=120.0, gt=0)
    #: Calls in flight at once, per ``base_url``, across the process.
    max_concurrency: int = Field(default=4, ge=1)
    verify_ssl: bool = True

    def api_key(self) -> str:
        """The key from the environment; empty when the variable is unset."""
        return os.environ.get(self.api_key_env, "")


class ReasoningOverride(BaseModel):
    """What one role changes; anything unset comes from the default."""

    model_config = ConfigDict(extra="forbid")

    base_url: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    max_concurrency: int | None = Field(default=None, ge=1)
    verify_ssl: bool | None = None


class ReasoningConfig(ReasoningEndpoint):
    """The required default endpoint, and per-role changes to it."""

    roles: dict[str, ReasoningOverride] = {}

    def for_role(self, role: str) -> ReasoningEndpoint:
        """The endpoint *role* uses: its override over the default."""
        default = ReasoningEndpoint(
            **self.model_dump(exclude={"roles"})
        )
        override = self.roles.get(role)
        if override is None:
            return default
        return default.model_copy(
            update=override.model_dump(exclude_none=True)
        )

    def problems(self) -> list[str]:
        """What keeps this config from working, one line each."""
        found = []
        for label, endpoint in self._endpoints():
            if not endpoint.base_url:
                found.append(f"{label}: base_url is empty")
            if not endpoint.model:
                found.append(f"{label}: model is empty")
            if not endpoint.api_key():
                found.append(
                    f"{label}: the API key variable {endpoint.api_key_env} "
                    "is not set"
                )
        return found

    def _endpoints(self) -> list[tuple[str, ReasoningEndpoint]]:
        roles = [(f"reasoning.roles.{r}", self.for_role(r)) for r in self.roles]
        return [("reasoning", self.for_role("")), *roles]
