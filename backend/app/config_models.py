"""Structured config models: dispatchable backends and task sources.

Extracted from :mod:`app.config` for cohesion and to keep that module within
its length budget. ``BackendConfig`` describes one agent backend; each
``TaskSourceConfig`` describes one origin of work items (GitHub or Jira) in the
file-only ``task_sources`` list. Secrets are never stored here — a model names
the environment variable that holds its token and resolves it on demand.
"""
from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, model_validator

#: Default env var holding each source type's token when ``token_env`` is unset.
_DEFAULT_TOKEN_ENV = {
    "github": "KESTREL_GITHUB_TOKEN",
    "jira": "KESTREL_JIRA_API_TOKEN",
}


class BackendConfig(BaseModel):
    """One dispatchable agent backend.

    ``type`` selects the adapter; the remaining fields configure it
    (``base_url``/``model``/``api_key_env`` are used by the HTTP-based
    backends added in later phases). ``caps`` overrides the adapter's
    default capabilities when set.
    """

    id: str
    type: Literal["claude_cli", "opencode", "openai_compat"] = "claude_cli"
    base_url: str | None = None
    model: str | None = None
    #: This backend's secret, given directly (fine in a gitignored config
    #: file): a bearer API key (``openai_compat``) or the HTTP Basic
    #: password (``opencode``). Prefer ``api_key`` / ``password``; these
    #: aliases are equivalent.
    api_key: str | None = None
    password: str | None = None
    #: Name of an env var holding the secret instead of giving it inline
    #: (used when the value is provided by the environment). Takes effect
    #: only when the direct secret above is unset.
    api_key_env: str | None = None
    #: HTTP Basic username for a secured ``opencode`` server. Defaults to
    #: opencode's own default ("opencode") when a password is configured.
    username: str | None = None
    #: Per-request timeout in seconds for HTTP backends (openai/opencode).
    timeout: float | None = None
    caps: list[str] | None = None

    def secret(self) -> str | None:
        """The resolved secret: an inline value, else the named env var."""
        direct = self.api_key or self.password
        if direct:
            return direct
        return os.environ.get(self.api_key_env) if self.api_key_env else None


class TaskSourceConfig(BaseModel):
    """One configured origin of work items (a GitHub or Jira source).

    ``type`` discriminates the entry; the per-type fields below carry that
    source's selection criteria and (for Jira) its repository-resolution and
    code-host settings. Tokens stay in the environment: ``token_env`` names the
    variable holding this source's token (defaulting per type). Every entry
    lives in the file-only ``task_sources`` list.
    """

    type: Literal["github", "jira"]
    #: Name of the env var holding this source's token; defaults per type.
    token_env: str | None = None
    #: Verify TLS certificates on this source's REST/API calls (Jira and the
    #: code host). Set ``false`` for a self-hosted instance with an internal or
    #: self-signed CA the process does not trust. Does not affect ``git`` clone/
    #: push (which use the system trust store).
    verify_ssl: bool = True
    #: GitHub: allow-list of ``owner/name`` repos and the ingestion label.
    watched_repos: list[str] = []
    trigger_label: str = "kestrel"
    #: Jira: instance URL, auth, and the one whole JQL selecting qualifying
    #: RFCs (folds the former project key + filter).
    base_url: str = ""
    auth: Literal["basic", "bearer"] = "basic"
    email: str = ""
    jql: str = ""
    #: Jira: issue-key prefix (e.g. ``"RFC"``) used only to scope this source's
    #: dismissal-clear/re-trigger gesture — not part of item selection.
    key: str = ""
    #: Jira: optional custom field holding ``owner/name[@base]``; when unset the
    #: repo is resolved from a web link titled ``repo_link_text``.
    repo_field: str = ""
    repo_link_text: str = "Repository"
    #: Jira: code host for resolved repos and its (self-hosted) URL + token env.
    code_host: Literal["github", "gitlab", "gitea"] = "github"
    code_host_base_url: str = ""
    code_host_token_env: str | None = None

    @model_validator(mode="after")
    def _check_required(self) -> TaskSourceConfig:
        """Enforce the fields each source type needs (loud at startup)."""
        if self.type == "github" and not self.watched_repos:
            raise ValueError("github task source requires watched_repos")
        if self.type == "jira" and not (
            self.base_url and self.jql and self.key
        ):
            raise ValueError(
                "jira task source requires base_url, jql, and key"
            )
        return self

    def token(self) -> str | None:
        """Resolve this source's token from its (defaulted) env var."""
        env = self.token_env or _DEFAULT_TOKEN_ENV.get(self.type)
        return os.environ.get(env) if env else None

    def code_host_token(self) -> str | None:
        """Resolve the code-host token (github token when host is github)."""
        env = self.code_host_token_env or (
            "KESTREL_GITHUB_TOKEN"
            if self.code_host == "github"
            else "KESTREL_CODE_HOST_TOKEN"
        )
        return os.environ.get(env) if env else None
