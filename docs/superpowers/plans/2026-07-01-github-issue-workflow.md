# GitHub Issue → Code Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first real workflow — a human-in-the-loop pipeline (refine → plan → implement → draft PR) that turns a GitHub issue into a pull request, orchestrated over the existing session/streaming machinery.

**Architecture:** A singleton `WorkflowService` drives a `WorkflowRun` state machine in a background task, delegating each agent step to `SessionRunner`, git to `GitService`, and GitHub to `GitHubClient`. Each step streams live via the existing session SSE and yields a deliverable a human validates before the run proceeds. State is in-memory.

**Tech Stack:** FastAPI (uv), pydantic-settings, httpx (async, moved to a runtime dep), asyncio subprocess for `git` and `claude`, Vue 3 + Vuetify 4 + TypeScript (Vite, npm).

## Global Constraints

- Package manager: `uv` (backend), `npm` (frontend) — only. Run backend commands from `backend/`, frontend from `frontend/`.
- Layering: `routers → services → storage`, calls downward only. Routers hold no business logic; services hold no HTTP concepts.
- Cross-layer errors use domain exception classes, never built-in `KeyError`/`RuntimeError`. Map to explicit HTTP codes via handlers registered in `create_app`.
- TDD: write the failing test, watch it fail, minimal code to pass, commit. Every backend test docstring starts with `"Ensure …"`.
- Frontend business types in `frontend/src/types/` mirror backend JSON shapes; keep in sync (`contract.md`).
- Secrets: `.env` stays gitignored; token never committed and never written into `.git/config` (injected per-command via `git -c http.extraheader`).
- GitHub is coded to public REST docs and mocked in unit tests — no live GitHub calls anywhere in the suite. `GitService` is tested against a local bare repo.
- Config prefix is `DISPATCHER_`; settings come from the pydantic `Settings` class.

---

## Task 1: Config, secrets, and httpx runtime dependency

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/pyproject.toml:7-11` (move `httpx` into `[project].dependencies`)
- Create: `backend/.env.example`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Produces: `Settings.github_token: str = ""`, `Settings.github_api_base: str = "https://api.github.com"`, `Settings.git_base: str = "https://github.com"` (all env-prefixed `DISPATCHER_`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_config.py
"""Tests for application settings."""
from __future__ import annotations

from app.config import Settings


def test_github_settings_have_defaults() -> None:
    """Ensure GitHub settings default to the public API and github.com."""
    s = Settings(github_token="")
    assert s.github_api_base == "https://api.github.com"
    assert s.git_base == "https://github.com"


def test_github_settings_read_env(monkeypatch) -> None:
    """Ensure the DISPATCHER_ env prefix populates GitHub settings."""
    monkeypatch.setenv("DISPATCHER_GITHUB_TOKEN", "tok-123")
    monkeypatch.setenv("DISPATCHER_GITHUB_API_BASE", "https://ghe.example/api/v3")
    s = Settings()
    assert s.github_token == "tok-123"
    assert s.github_api_base == "https://ghe.example/api/v3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -q`
Expected: FAIL — `Settings` has no `github_token`/`github_api_base`/`git_base`.

- [ ] **Step 3: Add the settings**

```python
# backend/app/config.py — add these fields to class Settings, after permission_mode
    github_token: str = ""
    github_api_base: str = "https://api.github.com"
    git_base: str = "https://github.com"
```

- [ ] **Step 4: Move httpx to a runtime dependency**

Edit `backend/pyproject.toml` — add `"httpx>=0.28.1"` to `[project].dependencies` and remove it from `[dependency-groups].dev`:

```toml
dependencies = [
    "fastapi>=0.138.2",
    "httpx>=0.28.1",
    "pydantic-settings>=2.14.2",
    "uvicorn[standard]>=0.49.0",
]

[dependency-groups]
dev = [
    "pytest>=9.1.1",
    "pytest-asyncio>=1.4.0",
]
```

- [ ] **Step 5: Create `backend/.env.example`**

```bash
# Copy to backend/.env and fill in. .env is gitignored — never commit it.
DISPATCHER_CLAUDE_BIN=claude
DISPATCHER_WORKSPACE_ROOT=./.dispatcher-workspaces
DISPATCHER_PERMISSION_MODE=acceptEdits

# GitHub workflow (leave token empty until you have one)
DISPATCHER_GITHUB_TOKEN=
DISPATCHER_GITHUB_API_BASE=https://api.github.com
DISPATCHER_GIT_BASE=https://github.com
```

- [ ] **Step 6: Run tests + sync deps**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS. (`uv run` re-syncs; confirm `httpx` still importable.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/config.py backend/pyproject.toml backend/uv.lock backend/.env.example backend/tests/test_config.py
git commit -m "feat(backend): add GitHub settings and make httpx a runtime dep"
```

---

## Task 2: Domain exceptions for workflows and integrations

**Files:**
- Modify: `backend/app/services/exceptions.py`
- Test: `backend/tests/test_workflow_exceptions.py`

**Interfaces:**
- Produces: `WorkflowNotFoundError(workflow_id: str)`, `InvalidWorkflowStateError(detail: str)`, `GitHubError(Exception)`, `GitError(Exception)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_workflow_exceptions.py
"""Tests for workflow domain exceptions."""
from __future__ import annotations

from app.services.exceptions import (
    InvalidWorkflowStateError,
    WorkflowNotFoundError,
)


def test_workflow_not_found_carries_id() -> None:
    """Ensure WorkflowNotFoundError records the missing id."""
    exc = WorkflowNotFoundError("wf-1")
    assert exc.workflow_id == "wf-1"


def test_invalid_state_carries_detail() -> None:
    """Ensure InvalidWorkflowStateError records a human detail."""
    exc = InvalidWorkflowStateError("not awaiting approval")
    assert "awaiting" in str(exc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_workflow_exceptions.py -q`
Expected: FAIL — names not importable.

- [ ] **Step 3: Add the exceptions**

```python
# backend/app/services/exceptions.py — append
class WorkflowNotFoundError(Exception):
    """Raised when an operation targets an unknown workflow id."""

    def __init__(self, workflow_id: str) -> None:
        """
        :param workflow_id: The workflow id that was not found.
        """
        self.workflow_id = workflow_id
        super().__init__(f"unknown workflow: {workflow_id}")


class InvalidWorkflowStateError(Exception):
    """Raised when reply/approve/reject hits the wrong phase."""


class GitHubError(Exception):
    """Raised when a GitHub API call fails."""


class GitError(Exception):
    """Raised when a git subprocess fails."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_workflow_exceptions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exceptions.py backend/tests/test_workflow_exceptions.py
git commit -m "feat(backend): add workflow and integration domain exceptions"
```

---

## Task 3: GitHubClient (mocked-httpx)

**Files:**
- Create: `backend/app/services/github.py`
- Test: `backend/tests/test_github_client.py`

**Interfaces:**
- Consumes: `GitHubError` (Task 2).
- Produces:
  - `@dataclass Issue(number: int, title: str, body: str)`
  - `class GitHubClient(base_url: str, token: str)` with
    `async get_issue(repo: str, number: int) -> Issue`,
    `async get_default_branch(repo: str) -> str`,
    `async update_issue(repo: str, number: int, body: str) -> None`,
    `async create_pull_request(repo: str, head: str, base: str, title: str, body: str, draft: bool = True) -> str` (returns `html_url`).
  - `repo` is `"owner/name"`; paths are `/repos/{repo}/…`.

- [ ] **Step 1: Write the failing tests** (using `httpx.MockTransport`)

```python
# backend/tests/test_github_client.py
"""Tests for the GitHub REST client (transport mocked)."""
from __future__ import annotations

import json

import httpx
import pytest

from app.services.exceptions import GitHubError
from app.services.github import GitHubClient, Issue


def _client(handler) -> GitHubClient:
    client = GitHubClient("https://api.github.com", "tok-123")
    client._http = httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )
    return client


@pytest.mark.asyncio
async def test_get_issue_parses_shape() -> None:
    """Ensure get_issue calls the right URL and parses the issue."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(
            200, json={"number": 7, "title": "Bug", "body": "desc"}
        )

    issue = await _client(handler).get_issue("o/r", 7)
    assert issue == Issue(number=7, title="Bug", body="desc")
    assert seen["url"] == "https://api.github.com/repos/o/r/issues/7"
    assert seen["auth"] == "Bearer tok-123"


@pytest.mark.asyncio
async def test_get_default_branch() -> None:
    """Ensure get_default_branch reads default_branch from the repo."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"default_branch": "main"})

    assert await _client(handler).get_default_branch("o/r") == "main"


@pytest.mark.asyncio
async def test_update_issue_sends_body() -> None:
    """Ensure update_issue PATCHes the issue with the new body."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["method"] = req.method
        seen["json"] = json.loads(req.content)
        return httpx.Response(200, json={"number": 7})

    await _client(handler).update_issue("o/r", 7, "new body")
    assert seen["method"] == "PATCH"
    assert seen["json"] == {"body": "new body"}


@pytest.mark.asyncio
async def test_create_pull_request_returns_html_url() -> None:
    """Ensure create_pull_request posts a draft PR and returns its url."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["json"] = json.loads(req.content)
        return httpx.Response(
            201, json={"html_url": "https://github.com/o/r/pull/9"}
        )

    url = await _client(handler).create_pull_request(
        "o/r", head="b", base="main", title="T", body="B"
    )
    assert url == "https://github.com/o/r/pull/9"
    assert seen["json"] == {
        "title": "T",
        "head": "b",
        "base": "main",
        "body": "B",
        "draft": True,
    }


@pytest.mark.asyncio
async def test_non_2xx_raises_github_error() -> None:
    """Ensure a non-2xx response raises GitHubError."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    with pytest.raises(GitHubError):
        await _client(handler).get_issue("o/r", 7)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_github_client.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the client**

```python
# backend/app/services/github.py
"""Async GitHub REST client (coded to the public API docs)."""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.services.exceptions import GitHubError


@dataclass
class Issue:
    """A GitHub issue, trimmed to what the workflow needs."""

    number: int
    title: str
    body: str


class GitHubClient:
    """Thin async wrapper over the GitHub REST API."""

    def __init__(self, base_url: str, token: str) -> None:
        """
        :param base_url: API base, e.g. https://api.github.com.
        :param token: Bearer token for the Authorization header.
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._http = httpx.AsyncClient(base_url=self.base_url)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(self, method: str, path: str, **kw) -> httpx.Response:
        resp = await self._http.request(
            method, path, headers=self._headers(), **kw
        )
        if resp.status_code >= 300:
            raise GitHubError(
                f"{method} {path} -> {resp.status_code}: {resp.text}"
            )
        return resp

    async def get_issue(self, repo: str, number: int) -> Issue:
        """Fetch an issue by number."""
        resp = await self._request("GET", f"/repos/{repo}/issues/{number}")
        data = resp.json()
        return Issue(
            number=data["number"],
            title=data.get("title", ""),
            body=data.get("body") or "",
        )

    async def get_default_branch(self, repo: str) -> str:
        """Return the repo's default branch (PR base)."""
        resp = await self._request("GET", f"/repos/{repo}")
        return resp.json()["default_branch"]

    async def update_issue(self, repo: str, number: int, body: str) -> None:
        """Replace an issue's body."""
        await self._request(
            "PATCH", f"/repos/{repo}/issues/{number}", json={"body": body}
        )

    async def create_pull_request(
        self,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
        draft: bool = True,
    ) -> str:
        """Open a pull request and return its html_url."""
        resp = await self._request(
            "POST",
            f"/repos/{repo}/pulls",
            json={
                "title": title,
                "head": head,
                "base": base,
                "body": body,
                "draft": draft,
            },
        )
        return resp.json()["html_url"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_github_client.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/github.py backend/tests/test_github_client.py
git commit -m "feat(backend): add async GitHubClient (mocked-httpx tested)"
```

---

## Task 4: GitService (local-bare-repo tested)

**Files:**
- Create: `backend/app/services/git.py`
- Test: `backend/tests/test_git_service.py`

**Interfaces:**
- Consumes: `GitError` (Task 2).
- Produces: `class GitService(token: str)` with
  `async clone(remote_url: str, dest: str) -> None`,
  `async checkout_branch(dest: str, branch: str) -> None`,
  `async commit_all(dest: str, message: str) -> None`,
  `async push(dest: str, branch: str) -> None`,
  `async diff(dest: str) -> str`.

- [ ] **Step 1: Write the failing test** (real git against a local bare remote)

```python
# backend/tests/test_git_service.py
"""Tests for GitService against a local bare repo (no network)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.git import GitService


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def _seed_bare_remote(tmp_path: Path) -> Path:
    """Create a bare remote with one commit on main."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _run("git", "init", "-b", "main", cwd=seed)
    _run("git", "config", "user.email", "t@t.io", cwd=seed)
    _run("git", "config", "user.name", "t", cwd=seed)
    (seed / "README.md").write_text("hi\n")
    _run("git", "add", "-A", cwd=seed)
    _run("git", "commit", "-m", "init", cwd=seed)
    bare = tmp_path / "remote.git"
    _run("git", "clone", "--bare", str(seed), str(bare), cwd=tmp_path)
    return bare


@pytest.mark.asyncio
async def test_clone_branch_commit_push_roundtrip(tmp_path) -> None:
    """Ensure clone/branch/commit/push land a branch on the remote."""
    bare = _seed_bare_remote(tmp_path)
    dest = str(tmp_path / "work")
    svc = GitService(token="unused-locally")

    await svc.clone(str(bare), dest)
    await svc.checkout_branch(dest, "dispatcher/issue-1")
    (Path(dest) / "new.txt").write_text("change\n")
    diff = await svc.diff(dest)
    assert "new.txt" in diff
    await svc.commit_all(dest, "work: add file")
    await svc.push(dest, "dispatcher/issue-1")

    branches = subprocess.run(
        ["git", "branch", "--list", "dispatcher/issue-1"],
        cwd=bare, check=True, capture_output=True, text=True,
    ).stdout
    assert "dispatcher/issue-1" in branches
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_git_service.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement GitService**

```python
# backend/app/services/git.py
"""Async wrapper over the git CLI for workflow git operations."""
from __future__ import annotations

import asyncio

from app.services.exceptions import GitError


class GitService:
    """Runs git commands; injects auth per-command, never into config."""

    def __init__(self, token: str) -> None:
        """
        :param token: Token used for the http.extraheader on remote ops.
        """
        self.token = token

    async def _git(self, *args: str, cwd: str | None = None) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} -> {proc.returncode}: "
                f"{err.decode('utf-8', 'replace')}"
            )
        return out.decode("utf-8", "replace")

    def _auth(self) -> list[str]:
        # Injected per-command so the token never persists in .git/config.
        # Ignored by git for non-http remotes (e.g. local bare repos).
        return ["-c", f"http.extraheader=AUTHORIZATION: bearer {self.token}"]

    async def clone(self, remote_url: str, dest: str) -> None:
        """Clone a remote into dest."""
        await self._git(*self._auth(), "clone", remote_url, dest)
        # Identity for commits made in this workspace.
        await self._git("config", "user.email", "dispatcher@local", cwd=dest)
        await self._git("config", "user.name", "agent-dispatcher", cwd=dest)

    async def checkout_branch(self, dest: str, branch: str) -> None:
        """Create and switch to a new branch."""
        await self._git("checkout", "-b", branch, cwd=dest)

    async def diff(self, dest: str) -> str:
        """Return the working-tree diff including untracked files."""
        await self._git("add", "-A", cwd=dest)
        return await self._git("diff", "--cached", cwd=dest)

    async def commit_all(self, dest: str, message: str) -> None:
        """Stage everything and commit."""
        await self._git("add", "-A", cwd=dest)
        await self._git("commit", "-m", message, cwd=dest)

    async def push(self, dest: str, branch: str) -> None:
        """Push a branch to origin."""
        await self._git(
            *self._auth(), "push", "origin", branch, cwd=dest
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_git_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/git.py backend/tests/test_git_service.py
git commit -m "feat(backend): add GitService tested against a local bare repo"
```

---

## Task 5: Workflow text helpers (sentinel + refined-issue extraction)

**Files:**
- Create: `backend/app/services/workflow_text.py`
- Test: `backend/tests/test_workflow_text.py`

**Interfaces:**
- Produces: `SENTINEL: str`, `has_sentinel(body: str) -> bool`, `append_sentinel(body: str) -> str`, `extract_refined_issue(text: str) -> str | None`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_workflow_text.py
"""Tests for workflow text helpers."""
from __future__ import annotations

from app.services.workflow_text import (
    SENTINEL,
    append_sentinel,
    extract_refined_issue,
    has_sentinel,
)


def test_has_sentinel_detects_marker() -> None:
    """Ensure has_sentinel is true only when the marker is present."""
    assert has_sentinel(f"body\n{SENTINEL}") is True
    assert has_sentinel("plain body") is False


def test_append_sentinel_is_idempotent() -> None:
    """Ensure append_sentinel adds the marker once."""
    once = append_sentinel("body")
    twice = append_sentinel(once)
    assert has_sentinel(once)
    assert once == twice


def test_extract_refined_issue_between_delimiters() -> None:
    """Ensure the refined issue is extracted from the delimiter block."""
    text = "chatter\n<REFINED_ISSUE>\nThe refined text\n</REFINED_ISSUE>\nmore"
    assert extract_refined_issue(text) == "The refined text"


def test_extract_refined_issue_absent_returns_none() -> None:
    """Ensure output without the delimiter yields None (still questions)."""
    assert extract_refined_issue("Just a question?") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflow_text.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the helpers**

```python
# backend/app/services/workflow_text.py
"""Sentinel and refined-issue extraction helpers for the workflow."""
from __future__ import annotations

import re

SENTINEL = "<!-- agent-dispatcher:refined -->"

_REFINED = re.compile(
    r"<REFINED_ISSUE>\s*(.*?)\s*</REFINED_ISSUE>", re.DOTALL
)


def has_sentinel(body: str) -> bool:
    """Return True if the issue body was already refined."""
    return SENTINEL in body


def append_sentinel(body: str) -> str:
    """Append the sentinel to a body, at most once."""
    if has_sentinel(body):
        return body
    return f"{body.rstrip()}\n\n{SENTINEL}\n"


def extract_refined_issue(text: str) -> str | None:
    """Return the refined issue if the agent emitted the delimiter block."""
    match = _REFINED.search(text)
    return match.group(1).strip() if match else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_workflow_text.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/workflow_text.py backend/tests/test_workflow_text.py
git commit -m "feat(backend): add sentinel + refined-issue text helpers"
```

---

## Task 6: Workflow models and registry

**Files:**
- Create: `backend/app/models_workflow.py`
- Create: `backend/app/storage/workflow_registry.py`
- Test: `backend/tests/test_workflow_registry.py`

**Interfaces:**
- Produces:
  - `@dataclass WorkflowStep(name: str, session_id: str | None = None, status: str = "pending", deliverable: str | None = None)`
  - `@dataclass WorkflowRun(id, repo, issue_number, issue_title="", base_branch="", branch="", workspace="", status="pending", steps: list[WorkflowStep] = [], pr_url=None, error=None)`
  - `class WorkflowRegistry` with `create(run) -> WorkflowRun`, `get(id) -> WorkflowRun | None`, `list() -> list[WorkflowRun]`.
  - `get_workflow_registry() -> WorkflowRegistry` (lru_cache singleton).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_workflow_registry.py
"""Tests for the in-memory workflow registry."""
from __future__ import annotations

from app.models_workflow import WorkflowRun, WorkflowStep
from app.storage.workflow_registry import WorkflowRegistry


def test_create_get_list() -> None:
    """Ensure runs can be created, fetched, and listed."""
    reg = WorkflowRegistry()
    run = WorkflowRun(
        id="wf-1", repo="o/r", issue_number=3,
        steps=[WorkflowStep(name="refine")],
    )
    reg.create(run)
    assert reg.get("wf-1") is run
    assert reg.get("missing") is None
    assert [r.id for r in reg.list()] == ["wf-1"]
    assert reg.get("wf-1").steps[0].status == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_workflow_registry.py -q`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement models and registry**

```python
# backend/app/models_workflow.py
"""Domain models for workflow runs."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WorkflowStep:
    """One step of a workflow run, with its deliverable."""

    name: str
    session_id: str | None = None
    status: str = "pending"
    deliverable: str | None = None


@dataclass
class WorkflowRun:
    """A GitHub issue -> code workflow run."""

    id: str
    repo: str
    issue_number: int
    issue_title: str = ""
    base_branch: str = ""
    branch: str = ""
    workspace: str = ""
    status: str = "pending"
    steps: list[WorkflowStep] = field(default_factory=list)
    pr_url: str | None = None
    error: str | None = None
```

```python
# backend/app/storage/workflow_registry.py
"""In-memory registry of workflow runs."""
from __future__ import annotations

from functools import lru_cache

from app.models_workflow import WorkflowRun


class WorkflowRegistry:
    """Stores workflow runs in insertion order."""

    def __init__(self) -> None:
        self._runs: dict[str, WorkflowRun] = {}

    def create(self, run: WorkflowRun) -> WorkflowRun:
        """Store a new run and return it."""
        self._runs[run.id] = run
        return run

    def get(self, workflow_id: str) -> WorkflowRun | None:
        """Return a run by id, or None."""
        return self._runs.get(workflow_id)

    def list(self) -> list[WorkflowRun]:
        """Return all runs in insertion order."""
        return list(self._runs.values())


@lru_cache
def get_workflow_registry() -> WorkflowRegistry:
    """Return the process-wide WorkflowRegistry singleton."""
    return WorkflowRegistry()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_workflow_registry.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models_workflow.py backend/app/storage/workflow_registry.py backend/tests/test_workflow_registry.py
git commit -m "feat(backend): add workflow models and in-memory registry"
```

---

## Task 7: Extend SessionRunner for caller-controlled runs

The workflow needs to run `claude` in a specific cwd, with a specific permission mode, and **await completion** (to capture the deliverable) while still streaming live to the registry.

**Files:**
- Modify: `backend/app/services/runner.py`
- Test: `backend/tests/test_runner.py` (add)

**Interfaces:**
- Consumes: existing `build_argv`, `consume`, `SessionStartError`, `_stdout`/`_drain_stderr` scaffolding.
- Produces:
  - `build_argv(prompt, resume_id=None, permission_mode=None)` — `permission_mode` overrides the settings default.
  - `async run_blocking(prompt: str, cwd: str, permission_mode: str, resume_id: str | None = None, on_session_id: Callable[[str], None] | None = None) -> str` — spawns, streams to the registry live, awaits completion, returns the session id.

- [ ] **Step 1: Write the failing test** (reuse the streaming mock from Task nearby)

```python
# backend/tests/test_runner.py — add this test (imports already present:
#   asyncio, textwrap, Path, Settings, SessionRunner, SessionRegistry,
#   _drain_background, _streaming_claude)
@pytest.mark.asyncio
async def test_run_blocking_streams_and_awaits(tmp_path) -> None:
    """Ensure run_blocking streams to the registry and returns on completion."""
    settings = Settings(
        claude_bin=str(_streaming_claude(tmp_path)),
        workspace_root=str(tmp_path / "ws"),
        permission_mode="acceptEdits",
    )
    reg = SessionRegistry()
    runner = SessionRunner(settings, reg)
    cwd = str(tmp_path / "step")

    seen: list[str] = []
    sid = await runner.run_blocking(
        "hi", cwd=cwd, permission_mode="plan",
        on_session_id=lambda s: seen.append(s),
    )

    # Returned only after completion: result event present, status idle.
    assert sid == "stream-1"
    assert seen == ["stream-1"]
    rec = reg.get(sid)
    assert rec.status == "idle"
    assert any(e.type == "result" for e in rec.events)
    await _drain_background()


def test_build_argv_permission_mode_override() -> None:
    """Ensure build_argv honours a permission-mode override."""
    settings = Settings(
        claude_bin="claude", workspace_root="/tmp/ws",
        permission_mode="acceptEdits",
    )
    argv = SessionRunner(settings, SessionRegistry()).build_argv(
        "p", permission_mode="plan"
    )
    assert argv[argv.index("--permission-mode") + 1] == "plan"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_runner.py -k "run_blocking or permission_mode_override" -q`
Expected: FAIL — `run_blocking` missing; override unsupported.

- [ ] **Step 3: Refactor scaffolding into helpers + add the method**

In `backend/app/services/runner.py`, add module-level helpers (near `_TASKS`):

```python
async def _stdout_lines(proc: asyncio.subprocess.Process):
    assert proc.stdout is not None
    async for raw in proc.stdout:
        yield raw.decode("utf-8", "replace")


async def _drain(stream) -> None:
    async for _ in stream:
        pass
```

Update `build_argv` signature and body:

```python
    def build_argv(
        self,
        prompt: str,
        resume_id: str | None = None,
        permission_mode: str | None = None,
    ) -> list[str]:
        """Build the claude CLI argument vector.

        :param permission_mode: Overrides the settings default when given.
        """
        argv = [
            self.settings.claude_bin,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            permission_mode or self.settings.permission_mode,
        ]
        if resume_id is not None:
            argv += ["--resume", resume_id]
        return argv
```

Add `run_blocking` (below `_launch`):

```python
    async def run_blocking(
        self,
        prompt: str,
        cwd: str,
        permission_mode: str,
        resume_id: str | None = None,
        on_session_id: Callable[[str], None] | None = None,
    ) -> str:
        """
        Run a claude step to completion, streaming events live.

        Unlike start/resume (which return early and stream in the
        background), this awaits the subprocess so the caller can read
        the finished session's deliverable. Events still reach
        subscribers live as they arrive.

        :returns: The resolved session id.
        :raises SessionStartError: If no session id is produced.
        """
        os.makedirs(cwd, exist_ok=True)
        argv = self.build_argv(prompt, resume_id, permission_mode)
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stderr_task = asyncio.create_task(_drain(proc.stderr))
        try:
            sid = await self.consume(
                _stdout_lines(proc), cwd, resume_id, on_session_id
            )
            await proc.wait()
            await stderr_task
        finally:
            if proc.returncode is None:
                proc.kill()
            stderr_task.cancel()
        if sid is None:
            raise SessionStartError("claude produced no session id")
        return sid
```

- [ ] **Step 4: Run the whole runner suite**

Run: `uv run pytest tests/test_runner.py -q`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/runner.py backend/tests/test_runner.py
git commit -m "feat(backend): add run_blocking + permission-mode override to runner"
```

---

## Task 8: WorkflowService orchestration

**Files:**
- Create: `backend/app/services/workflows.py`
- Test: `backend/tests/test_workflow_service.py`

**Interfaces:**
- Consumes: `SessionRunner.run_blocking`, `GitService`, `GitHubClient`, `WorkflowRegistry`, `SessionRegistry`, text helpers, exceptions.
- Produces:
  - `class WorkflowService(settings, sessions, workflows, runner, git, github)` with
    `async create(repo: str, issue_number: int) -> str`,
    `def get(workflow_id) -> WorkflowRun` (raises `WorkflowNotFoundError`),
    `def list() -> list[WorkflowRun]`,
    `def reply(workflow_id, text)` (raises `InvalidWorkflowStateError`),
    `def approve(workflow_id, deliverable: str | None = None)`,
    `def reject(workflow_id)`,
    `def current_session_id(run) -> str | None`.
  - `get_workflow_service() -> WorkflowService` (lru_cache singleton).

**Design notes for the implementer (all realised in the code below):**
- Async coordination lives in a parallel `_Control` per run (an approval `Future` and a reply `Queue`), kept in a `dict` on the singleton service — never on the serialisable `WorkflowRun`.
- `create` builds the run + control, stores it, and launches `_drive` as a background task held in a module-level set (so it outlives the request).
- Prompts are module constants. The refine loop resumes the same refine session; implement resumes the plan session.

- [ ] **Step 1: Write the failing tests** (fakes for runner/git/github)

```python
# backend/tests/test_workflow_service.py
"""Tests for the WorkflowService state machine (integrations faked)."""
from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.models import ParsedEvent, SessionRecord
from app.services.exceptions import (
    InvalidWorkflowStateError,
    WorkflowNotFoundError,
)
from app.services.github import Issue
from app.services.workflows import WorkflowService
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry


class _FakeGit:
    def __init__(self) -> None:
        self.pushed: list[str] = []

    async def clone(self, remote_url: str, dest: str) -> None: ...
    async def checkout_branch(self, dest: str, branch: str) -> None: ...
    async def commit_all(self, dest: str, message: str) -> None: ...
    async def diff(self, dest: str) -> str:
        return "diff --git a/x b/x"
    async def push(self, dest: str, branch: str) -> None:
        self.pushed.append(branch)


class _FakeGitHub:
    def __init__(self, body: str = "Please add a widget") -> None:
        self.body = body
        self.updated: str | None = None

    async def get_issue(self, repo: str, number: int) -> Issue:
        return Issue(number=number, title="Add widget", body=self.body)
    async def get_default_branch(self, repo: str) -> str:
        return "main"
    async def update_issue(self, repo: str, number: int, body: str) -> None:
        self.updated = body
    async def create_pull_request(self, repo, head, base, title, body,
                                  draft=True) -> str:
        return "https://github.com/o/r/pull/1"


class _FakeRunner:
    """Records a session with a canned final result text per call."""

    def __init__(self, sessions: SessionRegistry, outputs: list[str]) -> None:
        self.sessions = sessions
        self._outputs = list(outputs)
        self._n = 0

    async def run_blocking(self, prompt, cwd, permission_mode,
                           resume_id=None, on_session_id=None) -> str:
        sid = resume_id or f"s{self._n}"
        self._n += 1
        text = self._outputs.pop(0)
        if self.sessions.get(sid) is None:
            self.sessions._records[sid] = SessionRecord(session_id=sid, cwd=cwd)
        rec = self.sessions.get(sid)
        rec.events.append(ParsedEvent("result", sid, {"result": text}))
        rec.status = "idle"
        if on_session_id:
            on_session_id(sid)
        return sid


def _service(github, runner, git) -> WorkflowService:
    return WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        runner=runner,
        git=git,
        github=github,
    )


async def _wait(pred, timeout=2.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached")


@pytest.mark.asyncio
async def test_happy_path_refine_plan_implement_pr() -> None:
    """Ensure a run refines, plans, implements, and opens a PR."""
    gh = _FakeGitHub(body="vague issue")
    git = _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<REFINED_ISSUE>\nBuild a clear widget\n</REFINED_ISSUE>",  # refine
        "The plan: do X then Y",                                    # plan
        "Implemented X and Y",                                      # implement
    ])
    svc = _service(gh, runner, git)

    wid = await svc.create("o/r", 5)

    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    assert svc.get(wid).steps[0].deliverable == "Build a clear widget"
    svc.approve(wid)  # writes issue + sentinel, advances to plan

    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    assert "plan" in svc.get(wid).steps[1].deliverable.lower()
    assert gh.updated is not None and "agent-dispatcher:refined" in gh.updated
    svc.approve(wid)

    await _wait(lambda: svc.get(wid).status == "awaiting_implement_approval")
    assert "diff" in svc.get(wid).steps[2].deliverable
    svc.approve(wid)

    await _wait(lambda: svc.get(wid).status == "done")
    assert svc.get(wid).pr_url == "https://github.com/o/r/pull/1"
    assert git.pushed == [svc.get(wid).branch]


@pytest.mark.asyncio
async def test_sentinel_skips_refine() -> None:
    """Ensure an already-refined issue jumps straight to plan."""
    gh = _FakeGitHub(body="clear issue\n\n<!-- agent-dispatcher:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "The plan", "Implemented",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    assert svc.get(wid).steps[0].status == "done"  # refine skipped


@pytest.mark.asyncio
async def test_reject_ends_run() -> None:
    """Ensure rejecting a gate ends the run as rejected."""
    gh = _FakeGitHub(body="x\n\n<!-- agent-dispatcher:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=["The plan"])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    svc.reject(wid)
    await _wait(lambda: svc.get(wid).status == "rejected")


def test_get_unknown_raises() -> None:
    """Ensure get on an unknown id raises WorkflowNotFoundError."""
    svc = _service(_FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]),
                   _FakeGit())
    with pytest.raises(WorkflowNotFoundError):
        svc.get("nope")


def test_reply_wrong_state_raises() -> None:
    """Ensure reply outside the refine interview raises InvalidWorkflowState."""
    svc = _service(_FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]),
                   _FakeGit())
    import uuid
    from app.models_workflow import WorkflowRun, WorkflowStep
    run = WorkflowRun(id="wf", repo="o/r", issue_number=1,
                      steps=[WorkflowStep(name="refine", status="pending")])
    svc.workflows.create(run)
    svc._control["wf"] = svc._new_control()
    with pytest.raises(InvalidWorkflowStateError):
        svc.reply("wf", "an answer")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflow_service.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the service**

```python
# backend/app/services/workflows.py
"""Orchestrates the GitHub issue -> code workflow over sessions."""
from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field

from app.config import Settings, get_settings
from app.models_workflow import WorkflowRun, WorkflowStep
from app.services.exceptions import (
    InvalidWorkflowStateError,
    WorkflowNotFoundError,
)
from app.services.git import GitService
from app.services.github import GitHubClient
from app.services.runner import SessionRunner, get_runner
from app.services.workflow_text import (
    append_sentinel,
    extract_refined_issue,
    has_sentinel,
)
from app.storage.registry import SessionRegistry, get_registry
from app.storage.workflow_registry import (
    WorkflowRegistry,
    get_workflow_registry,
)

_WF_TASKS: set[asyncio.Task] = set()

REFINE_PROMPT = (
    "You are refining a GitHub issue before implementation. Read the issue "
    "below and the surrounding codebase. Ask clarifying, interview-style "
    "questions ONE round at a time. When you have enough detail, output the "
    "complete refined issue wrapped EXACTLY in <REFINED_ISSUE> and "
    "</REFINED_ISSUE> tags and nothing else. Do not edit any files.\n\n"
    "ISSUE:\n{issue}"
)
PLAN_PROMPT = (
    "Read this refined GitHub issue and the codebase, then produce a concise "
    "implementation plan. Do not edit any files.\n\nISSUE:\n{issue}"
)
IMPLEMENT_PROMPT = (
    "Implement the plan you just produced. Make all necessary code edits in "
    "this repository now."
)


@dataclass
class _Control:
    """Async coordination for one run (kept off the serialisable model)."""

    gate: asyncio.Future = field(default_factory=asyncio.get_event_loop().create_future)
    replies: asyncio.Queue = field(default_factory=asyncio.Queue)


@dataclass
class _Decision:
    approved: bool
    deliverable: str | None = None


class WorkflowService:
    """Drives workflow runs through refine -> plan -> implement -> PR."""

    def __init__(
        self,
        settings: Settings,
        sessions: SessionRegistry,
        workflows: WorkflowRegistry,
        runner: SessionRunner,
        git: GitService,
        github: GitHubClient,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.workflows = workflows
        self.runner = runner
        self.git = git
        self.github = github
        self._control: dict[str, _Control] = {}

    def _new_control(self) -> _Control:
        loop = asyncio.get_event_loop()
        return _Control(gate=loop.create_future(), replies=asyncio.Queue())

    # ---- queries -------------------------------------------------------
    def get(self, workflow_id: str) -> WorkflowRun:
        run = self.workflows.get(workflow_id)
        if run is None:
            raise WorkflowNotFoundError(workflow_id)
        return run

    def list(self) -> list[WorkflowRun]:
        return self.workflows.list()

    def current_session_id(self, run: WorkflowRun) -> str | None:
        for step in run.steps:
            if step.status in ("running", "awaiting_input", "awaiting_approval"):
                return step.session_id
        return None

    # ---- commands ------------------------------------------------------
    async def create(self, repo: str, issue_number: int) -> str:
        run = WorkflowRun(
            id="wf-" + uuid.uuid4().hex[:8],
            repo=repo,
            issue_number=issue_number,
            branch=f"dispatcher/issue-{issue_number}",
            workspace=os.path.join(
                self.settings.workspace_root,
                f"wf-{uuid.uuid4().hex[:8]}",
            ),
            steps=[
                WorkflowStep(name="refine"),
                WorkflowStep(name="plan"),
                WorkflowStep(name="implement"),
            ],
        )
        self.workflows.create(run)
        self._control[run.id] = self._new_control()
        task = asyncio.create_task(self._drive(run.id))
        _WF_TASKS.add(task)
        task.add_done_callback(_WF_TASKS.discard)
        return run.id

    def reply(self, workflow_id: str, text: str) -> None:
        run = self.get(workflow_id)
        step = run.steps[0]
        if step.name != "refine" or step.status != "awaiting_input":
            raise InvalidWorkflowStateError("not awaiting a refine reply")
        self._control[workflow_id].replies.put_nowait(text)

    def approve(self, workflow_id: str, deliverable: str | None = None) -> None:
        self._resolve(workflow_id, _Decision(True, deliverable))

    def reject(self, workflow_id: str) -> None:
        self._resolve(workflow_id, _Decision(False))

    def _resolve(self, workflow_id: str, decision: _Decision) -> None:
        run = self.get(workflow_id)
        control = self._control[workflow_id]
        if control.gate.done():
            raise InvalidWorkflowStateError("no gate awaiting a decision")
        control.gate.set_result(decision)

    # ---- orchestration -------------------------------------------------
    async def _await_gate(self, workflow_id: str) -> _Decision:
        control = self._control[workflow_id]
        decision = await control.gate
        control.gate = asyncio.get_event_loop().create_future()
        return decision

    def _result_text(self, session_id: str) -> str:
        rec = self.sessions.get(session_id)
        if rec is None:
            return ""
        for ev in reversed(rec.events):
            if ev.type == "result":
                value = ev.raw.get("result")
                return value if isinstance(value, str) else ""
        return ""

    async def _drive(self, workflow_id: str) -> None:
        run = self.get(workflow_id)
        try:
            run.status = "cloning"
            issue = await self.github.get_issue(run.repo, run.issue_number)
            run.issue_title = issue.title
            run.base_branch = await self.github.get_default_branch(run.repo)
            remote = f"{self.settings.git_base}/{run.repo}.git"
            await self.git.clone(remote, run.workspace)
            await self.git.checkout_branch(run.workspace, run.branch)

            if has_sentinel(issue.body):
                run.steps[0].status = "done"
                run.steps[0].deliverable = issue.body
            else:
                await self._refine(run, issue.body)

            await self._plan(run)
            await self._implement(run)

            run.status = "opening_pr"
            await self.git.commit_all(run.workspace, f"Implement #{run.issue_number}")
            await self.git.push(run.workspace, run.branch)
            run.pr_url = await self.github.create_pull_request(
                run.repo,
                head=run.branch,
                base=run.base_branch,
                title=f"{run.issue_title} (#{run.issue_number})",
                body=f"Closes #{run.issue_number}\n\nOpened by agent-dispatcher.",
            )
            run.status = "done"
        except _Rejected:
            run.status = "rejected"
        except Exception as exc:  # record, do not crash the loop
            run.status = "failed"
            run.error = str(exc)

    async def _refine(self, run: WorkflowRun, body: str) -> None:
        step = run.steps[0]
        prompt = REFINE_PROMPT.format(issue=body)
        sid: str | None = None
        while True:
            run.status = "refining"
            step.status = "running"
            sid = await self.runner.run_blocking(
                prompt, run.workspace, "plan", resume_id=sid,
                on_session_id=lambda s: setattr(step, "session_id", s),
            )
            refined = extract_refined_issue(self._result_text(sid))
            if refined is not None:
                step.deliverable = refined
                step.status = "awaiting_approval"
                run.status = "awaiting_refine_approval"
                decision = await self._await_gate(run.id)
                if not decision.approved:
                    raise _Rejected()
                final = decision.deliverable or refined
                await self.github.update_issue(
                    run.repo, run.issue_number, append_sentinel(final)
                )
                step.status = "done"
                return
            step.status = "awaiting_input"
            run.status = "awaiting_refine_input"
            prompt = await self._control[run.id].replies.get()

    async def _plan(self, run: WorkflowRun) -> None:
        step = run.steps[1]
        run.status = "planning"
        step.status = "running"
        refined = run.steps[0].deliverable or ""
        sid = await self.runner.run_blocking(
            PLAN_PROMPT.format(issue=refined), run.workspace, "plan",
            on_session_id=lambda s: setattr(step, "session_id", s),
        )
        step.deliverable = self._result_text(sid)
        step.status = "awaiting_approval"
        run.status = "awaiting_plan_approval"
        run.steps[1].session_id = sid
        decision = await self._await_gate(run.id)
        if not decision.approved:
            raise _Rejected()
        step.status = "done"
        self._plan_sid = sid  # for implement resume

    async def _implement(self, run: WorkflowRun) -> None:
        step = run.steps[2]
        run.status = "implementing"
        step.status = "running"
        sid = await self.runner.run_blocking(
            IMPLEMENT_PROMPT, run.workspace, "acceptEdits",
            resume_id=run.steps[1].session_id,
            on_session_id=lambda s: setattr(step, "session_id", s),
        )
        step.deliverable = await self.git.diff(run.workspace)
        step.status = "awaiting_approval"
        run.status = "awaiting_implement_approval"
        decision = await self._await_gate(run.id)
        if not decision.approved:
            raise _Rejected()
        step.status = "done"


class _Rejected(Exception):
    """Internal signal that a gate was rejected."""


def get_workflow_service() -> WorkflowService:
    """Return the process-wide WorkflowService singleton."""
    return _singleton()


from functools import lru_cache  # noqa: E402


@lru_cache
def _singleton() -> WorkflowService:
    settings = get_settings()
    registry = get_registry()
    return WorkflowService(
        settings=settings,
        sessions=registry,
        workflows=get_workflow_registry(),
        runner=SessionRunner(settings, registry),
        git=GitService(settings.github_token),
        github=GitHubClient(settings.github_api_base, settings.github_token),
    )
```

> Note for the implementer: the `_Control.gate` default_factory in the
> dataclass is replaced at runtime by `_new_control()`, which binds the
> future to the running loop — always construct controls via
> `_new_control()`, never the bare dataclass default.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_workflow_service.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest -q`
Expected: PASS, no warnings.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/workflows.py backend/tests/test_workflow_service.py
git commit -m "feat(backend): add WorkflowService orchestration (faked integrations)"
```

---

## Task 9: Schemas, router, and exception handlers

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/routers/workflows.py`
- Modify: `backend/app/main.py` (register router + handlers)
- Test: `backend/tests/test_workflows_router.py`

**Interfaces:**
- Consumes: `WorkflowService` + `get_workflow_service`, exceptions.
- Produces schemas: `WorkflowStepOut`, `WorkflowSummary`, `WorkflowDetail`, `CreateWorkflowIn`, `ReplyIn`, `ApproveIn`.
- Endpoints under `/api/workflows`: `POST /`, `GET /`, `GET /{id}`, `POST /{id}/reply`, `POST /{id}/approve`, `POST /{id}/reject`.

- [ ] **Step 1: Write the failing tests** (service faked via dependency override)

```python
# backend/tests/test_workflows_router.py
"""Tests for the workflows router (service mocked)."""
from __future__ import annotations

import httpx
import pytest

from app.main import create_app
from app.models_workflow import WorkflowRun, WorkflowStep
from app.services.exceptions import (
    InvalidWorkflowStateError,
    WorkflowNotFoundError,
)
from app.services.workflows import get_workflow_service


class _FakeService:
    def __init__(self) -> None:
        self.approved: list[str] = []

    async def create(self, repo: str, issue_number: int) -> str:
        return "wf-1"

    def list(self):
        return [WorkflowRun(id="wf-1", repo="o/r", issue_number=3,
                            status="planning")]

    def get(self, workflow_id: str) -> WorkflowRun:
        if workflow_id != "wf-1":
            raise WorkflowNotFoundError(workflow_id)
        return WorkflowRun(
            id="wf-1", repo="o/r", issue_number=3, issue_title="T",
            status="awaiting_plan_approval",
            steps=[WorkflowStep("refine", "s0", "done", "refined"),
                   WorkflowStep("plan", "s1", "awaiting_approval", "the plan"),
                   WorkflowStep("implement")],
        )

    def current_session_id(self, run) -> str:
        return "s1"

    def approve(self, workflow_id: str, deliverable=None) -> None:
        if workflow_id != "wf-1":
            raise WorkflowNotFoundError(workflow_id)
        self.approved.append(workflow_id)

    def reject(self, workflow_id: str) -> None: ...

    def reply(self, workflow_id: str, text: str) -> None:
        raise InvalidWorkflowStateError("not awaiting a refine reply")


def _client(service):
    app = create_app()
    app.dependency_overrides[get_workflow_service] = lambda: service
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_create_returns_id() -> None:
    """Ensure POST /api/workflows returns a workflow id."""
    async with _client(_FakeService()) as c:
        r = await c.post("/api/workflows", json={"repo": "o/r", "issue_number": 3})
    assert r.status_code == 200
    assert r.json()["workflow_id"] == "wf-1"


@pytest.mark.asyncio
async def test_detail_exposes_steps_and_current_session() -> None:
    """Ensure GET detail returns steps, deliverables, and current session."""
    async with _client(_FakeService()) as c:
        r = await c.get("/api/workflows/wf-1")
    body = r.json()
    assert r.status_code == 200
    assert body["current_session_id"] == "s1"
    assert body["steps"][1]["deliverable"] == "the plan"


@pytest.mark.asyncio
async def test_detail_unknown_returns_404() -> None:
    """Ensure an unknown workflow id maps to 404."""
    async with _client(_FakeService()) as c:
        r = await c.get("/api/workflows/nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_approve_ok_and_reply_conflict() -> None:
    """Ensure approve returns 200 and a bad reply maps to 409."""
    svc = _FakeService()
    async with _client(svc) as c:
        ok = await c.post("/api/workflows/wf-1/approve", json={})
        conflict = await c.post("/api/workflows/wf-1/reply", json={"text": "x"})
    assert ok.status_code == 200
    assert svc.approved == ["wf-1"]
    assert conflict.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflows_router.py -q`
Expected: FAIL — router/schemas/handlers missing.

- [ ] **Step 3: Add schemas**

```python
# backend/app/schemas.py — append
class WorkflowStepOut(BaseModel):
    """One workflow step for the API."""

    name: str
    session_id: str | None
    status: str
    deliverable: str | None


class WorkflowSummary(BaseModel):
    """Workflow list item."""

    id: str
    repo: str
    issue_number: int
    status: str


class WorkflowDetail(BaseModel):
    """Full workflow run for the detail endpoint."""

    id: str
    repo: str
    issue_number: int
    issue_title: str
    status: str
    branch: str
    steps: list[WorkflowStepOut]
    current_session_id: str | None
    pr_url: str | None
    error: str | None


class CreateWorkflowIn(BaseModel):
    """Request body to start a workflow."""

    repo: str
    issue_number: int


class ReplyIn(BaseModel):
    """Request body to answer the refine interview."""

    text: str


class ApproveIn(BaseModel):
    """Request body to approve a gate, optionally with an edited deliverable."""

    deliverable: str | None = None
```

- [ ] **Step 4: Add the router**

```python
# backend/app/routers/workflows.py
"""HTTP routes for GitHub issue -> code workflows."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.models_workflow import WorkflowRun
from app.schemas import (
    ApproveIn,
    CreateWorkflowIn,
    ReplyIn,
    WorkflowDetail,
    WorkflowStepOut,
    WorkflowSummary,
)
from app.services.workflows import WorkflowService, get_workflow_service

router = APIRouter(prefix="/api/workflows")


def _detail(service: WorkflowService, run: WorkflowRun) -> WorkflowDetail:
    return WorkflowDetail(
        id=run.id,
        repo=run.repo,
        issue_number=run.issue_number,
        issue_title=run.issue_title,
        status=run.status,
        branch=run.branch,
        steps=[
            WorkflowStepOut(
                name=s.name, session_id=s.session_id,
                status=s.status, deliverable=s.deliverable,
            )
            for s in run.steps
        ],
        current_session_id=service.current_session_id(run),
        pr_url=run.pr_url,
        error=run.error,
    )


@router.post("")
async def create_workflow(
    body: CreateWorkflowIn,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """Start a workflow and return its id."""
    wid = await service.create(body.repo, body.issue_number)
    return {"workflow_id": wid}


@router.get("", response_model=list[WorkflowSummary])
async def list_workflows(
    service: WorkflowService = Depends(get_workflow_service),
) -> list[WorkflowSummary]:
    """List all workflow runs."""
    return [
        WorkflowSummary(
            id=r.id, repo=r.repo, issue_number=r.issue_number, status=r.status
        )
        for r in service.list()
    ]


@router.get("/{workflow_id}", response_model=WorkflowDetail)
async def get_workflow(
    workflow_id: str,
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowDetail:
    """Return a workflow's full detail."""
    return _detail(service, service.get(workflow_id))


@router.post("/{workflow_id}/reply")
async def reply_workflow(
    workflow_id: str,
    body: ReplyIn,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """Answer the refine interview."""
    service.reply(workflow_id, body.text)
    return {"status": "ok"}


@router.post("/{workflow_id}/approve")
async def approve_workflow(
    workflow_id: str,
    body: ApproveIn,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """Approve the current gate (optionally with an edited deliverable)."""
    service.approve(workflow_id, body.deliverable)
    return {"status": "ok"}


@router.post("/{workflow_id}/reject")
async def reject_workflow(
    workflow_id: str,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """Reject the current gate and end the run."""
    service.reject(workflow_id)
    return {"status": "ok"}
```

- [ ] **Step 5: Register router + handlers in `create_app`**

```python
# backend/app/main.py — add imports
from app.services.exceptions import (
    InvalidWorkflowStateError,
    SessionNotFoundError,
    SessionStartError,
    WorkflowNotFoundError,
)

# inside create_app, alongside the existing handlers:
    @app.exception_handler(WorkflowNotFoundError)
    async def _workflow_not_found(request: Request, exc: WorkflowNotFoundError):
        """Map an unknown workflow to HTTP 404."""
        return JSONResponse(status_code=404, content={"detail": "unknown workflow"})

    @app.exception_handler(InvalidWorkflowStateError)
    async def _invalid_workflow_state(request: Request, exc: InvalidWorkflowStateError):
        """Map an invalid workflow transition to HTTP 409."""
        return JSONResponse(status_code=409, content={"detail": str(exc)})

# and register the router next to sessions:
    from app.routers import sessions, workflows

    app.include_router(sessions.router)
    app.include_router(workflows.router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_workflows_router.py -q`
Expected: PASS (4 tests).

- [ ] **Step 7: Run the full backend suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas.py backend/app/routers/workflows.py backend/app/main.py backend/tests/test_workflows_router.py
git commit -m "feat(backend): add workflows router, schemas, and handlers"
```

---

## Task 10: Frontend — types, API, and workflow composable

**Files:**
- Create: `frontend/src/types/workflows.ts`
- Create: `frontend/src/composables/useWorkflows.ts`
- Test: `frontend/tests/composables/useWorkflows.test.ts`

**Interfaces:**
- Consumes: `api` + `API_BASE` from `src/api/index.ts`; existing `SessionEvent` type.
- Produces: `useWorkflows()` exposing `workflows`, `current`, `events`, `error`, `refresh()`, `createWorkflow(repo, issueNumber)`, `select(id)`, `reply(text)`, `approve(deliverable?)`, `reject()`.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/tests/composables/useWorkflows.test.ts
import { describe, it, expect, vi, afterEach } from 'vitest'
import { useWorkflows } from '../../src/composables/useWorkflows'

afterEach(() => vi.restoreAllMocks())

describe('useWorkflows', () => {
  it('refresh populates workflows from the api', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify([
            { id: 'wf-1', repo: 'o/r', issue_number: 3, status: 'planning' },
          ]),
          { status: 200 },
        ),
      ),
    )
    const { workflows, refresh } = useWorkflows()
    await refresh()
    expect(workflows.value.map((w) => w.id)).toContain('wf-1')
  })

  it('createWorkflow posts repo and issue number', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ workflow_id: 'wf-9' }), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const { createWorkflow } = useWorkflows()
    const id = await createWorkflow('o/r', 5)
    expect(id).toBe('wf-9')
    const [, init] = fetchMock.mock.calls[0]
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      repo: 'o/r',
      issue_number: 5,
    })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm test -- useWorkflows`
Expected: FAIL — modules missing.

- [ ] **Step 3: Add types**

```typescript
// frontend/src/types/workflows.ts
export interface WorkflowStep {
  name: string
  session_id: string | null
  status: string
  deliverable: string | null
}

export interface WorkflowSummary {
  id: string
  repo: string
  issue_number: number
  status: string
}

export interface WorkflowDetail {
  id: string
  repo: string
  issue_number: number
  issue_title: string
  status: string
  branch: string
  steps: WorkflowStep[]
  current_session_id: string | null
  pr_url: string | null
  error: string | null
}
```

- [ ] **Step 4: Add the composable**

```typescript
// frontend/src/composables/useWorkflows.ts
import { ref } from 'vue'
import { api, API_BASE, ApiError } from '../api'
import type { SessionEvent } from '../types/sessions'
import type { WorkflowDetail, WorkflowSummary } from '../types/workflows'

const workflows = ref<WorkflowSummary[]>([])
const current = ref<WorkflowDetail | null>(null)
const events = ref<SessionEvent[]>([])
const error = ref<string | null>(null)

let source: EventSource | null = null
let poll: ReturnType<typeof setInterval> | null = null

function describe(e: unknown): string {
  if (e instanceof ApiError) return `Request failed (${e.status})`
  if (e instanceof Error) return e.message
  return 'Unexpected error'
}

export function useWorkflows() {
  async function refresh(): Promise<void> {
    workflows.value = await api.get<WorkflowSummary[]>('/api/workflows')
  }

  async function loadDetail(id: string): Promise<void> {
    const detail = await api.get<WorkflowDetail>(`/api/workflows/${id}`)
    // Re-subscribe to the live feed when the active step's session changes.
    if (detail.current_session_id &&
        detail.current_session_id !== current.value?.current_session_id) {
      watchSession(detail.current_session_id)
    }
    current.value = detail
  }

  function watchSession(sessionId: string): void {
    events.value = []
    if (source) source.close()
    source = new EventSource(`${API_BASE}/api/sessions/${sessionId}/events`)
    source.onmessage = (e) => {
      events.value.push(JSON.parse(e.data) as SessionEvent)
    }
  }

  function select(id: string): void {
    if (poll) clearInterval(poll)
    void loadDetail(id)
    poll = setInterval(() => void loadDetail(id), 1500)
  }

  async function createWorkflow(repo: string, issueNumber: number): Promise<string | null> {
    error.value = null
    try {
      const out = await api.post<{ workflow_id: string }>('/api/workflows', {
        repo,
        issue_number: issueNumber,
      })
      await refresh()
      select(out.workflow_id)
      return out.workflow_id
    } catch (e) {
      error.value = describe(e)
      return null
    }
  }

  async function reply(text: string): Promise<void> {
    if (current.value) await api.post(`/api/workflows/${current.value.id}/reply`, { text })
  }

  async function approve(deliverable?: string): Promise<void> {
    if (current.value)
      await api.post(`/api/workflows/${current.value.id}/approve`, { deliverable: deliverable ?? null })
  }

  async function reject(): Promise<void> {
    if (current.value) await api.post(`/api/workflows/${current.value.id}/reject`, {})
  }

  return { workflows, current, events, error, refresh, select, createWorkflow, reply, approve, reject }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm test -- useWorkflows`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/workflows.ts frontend/src/composables/useWorkflows.ts frontend/tests/composables/useWorkflows.test.ts
git commit -m "feat(frontend): add workflow types, api composable, and tests"
```

---

## Task 11: Frontend — Workflows panel and top-bar toggle

**Files:**
- Create: `frontend/src/components/WorkflowPanel.vue`
- Modify: `frontend/src/App.vue` (Sessions ⇄ Workflows toggle)

**Interfaces:**
- Consumes: `useWorkflows()` (Task 10), the Mission Control tokens in `styles/theme.css`, and the event-row rendering pattern from `SessionPanel.vue`.

- [ ] **Step 1: Create the WorkflowPanel component**

```vue
<!-- frontend/src/components/WorkflowPanel.vue -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useWorkflows } from '../composables/useWorkflows'

const { workflows, current, events, error, refresh, select, createWorkflow,
  reply, approve, reject } = useWorkflows()

const repo = ref('owner/name')
const issueNumber = ref<number>(1)
const answer = ref('')
const edited = ref('')

onMounted(refresh)

const STEP_LABELS = ['refine', 'plan', 'implement'] as const

const activeStep = computed(() =>
  current.value?.steps.find((s) =>
    ['running', 'awaiting_input', 'awaiting_approval'].includes(s.status)),
)
const awaitingInput = computed(() => activeStep.value?.status === 'awaiting_input')
const awaitingApproval = computed(() => activeStep.value?.status === 'awaiting_approval')

async function onCreate(): Promise<void> {
  await createWorkflow(repo.value, Number(issueNumber.value))
}
async function onApprove(): Promise<void> {
  await approve(edited.value || undefined)
  edited.value = ''
}
async function onReply(): Promise<void> {
  await reply(answer.value)
  answer.value = ''
}
function stepStatus(name: string): string {
  return current.value?.steps.find((s) => s.name === name)?.status ?? 'pending'
}
function stepTone(status: string): string {
  if (status === 'done') return 'ok'
  if (status === 'running' || status === 'awaiting_input') return 'agent'
  if (status === 'awaiting_approval') return 'warn'
  if (status === 'failed') return 'err'
  return 'sys'
}
</script>

<template>
  <div class="console">
    <aside class="rail">
      <div class="rail__block">
        <div class="eyebrow">New workflow</div>
        <input v-model="repo" class="field" placeholder="owner/name" />
        <input v-model="issueNumber" type="number" class="field" placeholder="Issue #" />
        <button class="btn btn--primary" @click="onCreate">
          <span aria-hidden="true">⟐</span> Start workflow
        </button>
      </div>
      <div class="rail__block rail__block--grow">
        <div class="rail__head">
          <span class="eyebrow">Runs</span>
          <span class="pill mono">{{ workflows.length }}</span>
        </div>
        <div class="sessions scroll">
          <button
            v-for="w in workflows"
            :key="w.id"
            class="scard"
            :class="{ 'scard--active': w.id === current?.id }"
            @click="select(w.id)"
          >
            <span class="scard__id mono">{{ w.repo }}#{{ w.issue_number }}</span>
            <span class="scard__meta">{{ w.status }}</span>
          </button>
          <p v-if="!workflows.length" class="sessions__empty mono">
            No workflows yet
          </p>
        </div>
      </div>
    </aside>

    <section class="stage">
      <div v-if="error" class="banner" role="alert">
        <span class="banner__glyph" aria-hidden="true">!</span>
        <span class="banner__text">{{ error }}</span>
        <button class="banner__close" @click="error = null">✕</button>
      </div>

      <header class="stage__head" v-if="current">
        <div class="stage__title">
          <span class="eyebrow">Workflow</span>
          <span class="stage__id mono">{{ current.repo }}#{{ current.issue_number }}</span>
        </div>
        <div class="tracker">
          <span
            v-for="name in STEP_LABELS"
            :key="name"
            class="tracker__step"
            :class="`t-${stepTone(stepStatus(name))}`"
          >
            <span class="tracker__dot" />{{ name }}
          </span>
          <span class="tracker__step" :class="current.pr_url ? 't-ok' : 't-sys'">
            <span class="tracker__dot" />PR
          </span>
        </div>
      </header>

      <div class="stage__body scroll" v-if="current">
        <div class="deliverable" v-if="activeStep?.deliverable">
          <div class="eyebrow">{{ activeStep.name }} deliverable</div>
          <pre class="deliverable__text mono">{{ activeStep.deliverable }}</pre>
        </div>

        <div class="gate" v-if="awaitingApproval">
          <textarea v-model="edited" class="field" rows="4"
            :placeholder="`Optionally edit the ${activeStep?.name} deliverable before approving…`" />
          <div class="gate__actions">
            <button class="btn btn--primary" @click="onApprove">Approve</button>
            <button class="btn btn--ghost" @click="reject">Reject</button>
          </div>
        </div>

        <div class="gate" v-if="awaitingInput">
          <textarea v-model="answer" class="field" rows="3"
            placeholder="Answer the agent's questions…" />
          <button class="btn btn--primary" @click="onReply">Send reply</button>
        </div>

        <a v-if="current.pr_url" class="pr-link" :href="current.pr_url" target="_blank"
          rel="noopener noreferrer">View pull request →</a>

        <div class="feed">
          <div class="eyebrow">Live telemetry</div>
          <div v-for="(e, i) in events" :key="i" class="ev-line mono">
            <span class="ev-line__type">{{ e.type }}</span>
            {{ JSON.stringify(e.raw).slice(0, 140) }}
          </div>
        </div>
      </div>

      <div class="feed__empty" v-else>
        <p class="feed__empty-title">No workflow selected</p>
        <p class="feed__empty-sub mono">Start one from an issue on the left.</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* Reuses tokens from styles/theme.css. Layout mirrors SessionPanel. */
.console { display: flex; height: 100%; min-height: 0; }
.rail {
  width: 340px; flex: none; display: flex; flex-direction: column; gap: 4px;
  padding: 22px 18px; border-right: 1px solid var(--line); background: var(--ink-800);
  overflow: hidden;
}
.rail__block {
  display: flex; flex-direction: column; gap: 10px; padding: 14px 0 18px;
  border-bottom: 1px solid var(--line-soft);
}
.rail__block:first-child { padding-top: 0; }
.rail__block--grow { flex: 1; min-height: 0; border-bottom: none; }
.rail__head { display: flex; align-items: center; justify-content: space-between; }
.pill {
  font-size: 11px; color: var(--text-mid); background: var(--ink-700);
  border: 1px solid var(--line); border-radius: 999px; padding: 1px 9px;
}
.sessions { margin-top: 12px; display: flex; flex-direction: column; gap: 8px;
  overflow-y: auto; min-height: 0; }
.scard {
  text-align: left; display: flex; flex-direction: column; gap: 6px;
  padding: 11px 13px; background: var(--ink-700); border: 1px solid var(--line);
  border-left: 2px solid var(--line); border-radius: var(--r-md); cursor: pointer;
}
.scard--active { border-left-color: var(--signal); background: var(--ink-650); }
.scard__id { font-size: 12.5px; color: var(--text-hi); }
.scard__meta { font-size: 11.5px; color: var(--text-mid); }
.sessions__empty { color: var(--text-dim); font-size: 12px; padding: 8px 2px; }
.stage { flex: 1; min-width: 0; display: flex; flex-direction: column; min-height: 0; }
.stage__head {
  flex: none; display: flex; align-items: center; justify-content: space-between;
  gap: 16px; padding: 20px 24px 18px; border-bottom: 1px solid var(--line);
}
.stage__title { display: flex; align-items: baseline; gap: 12px; }
.stage__id { font-size: 15px; color: var(--text-hi); }
.tracker { display: flex; gap: 14px; }
.tracker__step {
  --c: var(--idle); display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--c);
}
.tracker__dot { width: 8px; height: 8px; border-radius: 50%; background: var(--c); }
.t-sys { --c: var(--idle); } .t-agent { --c: var(--signal); }
.t-warn { --c: var(--warn); } .t-ok { --c: var(--ok); } .t-err { --c: var(--err); }
.stage__body { flex: 1; min-height: 0; overflow-y: auto; padding: 18px 24px; display: flex; flex-direction: column; gap: 18px; }
.deliverable__text {
  white-space: pre-wrap; word-break: break-word; background: var(--ink-750);
  border: 1px solid var(--line); border-radius: var(--r-md); padding: 12px 14px;
  font-size: 12.5px; color: var(--text-hi); margin: 6px 0 0;
}
.gate { display: flex; flex-direction: column; gap: 10px; }
.gate__actions { display: flex; gap: 10px; }
.gate__actions .btn { width: auto; padding-left: 22px; padding-right: 22px; }
.pr-link { color: var(--signal); font-weight: 600; text-decoration: none; }
.feed { display: flex; flex-direction: column; gap: 4px; }
.ev-line { font-size: 12px; color: var(--text-mid); }
.ev-line__type { color: var(--signal); margin-right: 8px; }
.banner {
  display: flex; align-items: center; gap: 12px; margin: 16px 24px 0;
  padding: 11px 14px; border: 1px solid var(--err); border-left: 3px solid var(--err);
  border-radius: var(--r-md); background: color-mix(in srgb, var(--err) 12%, var(--ink-800));
  font-size: 13px;
}
.banner__glyph {
  display: grid; place-items: center; width: 20px; height: 20px; flex: none;
  border-radius: 50%; background: var(--err); color: var(--ink-900); font-weight: 700;
}
.banner__text { flex: 1; }
.banner__close { background: none; border: none; color: var(--text-mid); cursor: pointer; }
.feed__empty {
  height: 100%; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 6px;
}
.feed__empty-title { margin: 0; font-size: 15px; font-weight: 600; color: var(--text-mid); }
.feed__empty-sub { margin: 0; font-size: 12px; color: var(--text-dim); }
</style>
```

- [ ] **Step 2: Add the Sessions ⇄ Workflows toggle to `App.vue`**

In `frontend/src/App.vue`, import both panels, add a `view` ref, a toggle in the top bar, and switch the main region:

```vue
<!-- script setup additions -->
import { computed, ref } from 'vue'
import SessionPanel from './components/SessionPanel.vue'
import WorkflowPanel from './components/WorkflowPanel.vue'
import { useSessions } from './composables/useSessions'

const view = ref<'sessions' | 'workflows'>('sessions')
const { sessions } = useSessions()
const running = computed(() => sessions.value.some((s) => s.status === 'running'))
```

```vue
<!-- template: replace the single <main> content and add a nav in the topbar -->
<nav class="viewnav">
  <button class="viewnav__btn" :class="{ 'viewnav__btn--on': view === 'sessions' }"
    @click="view = 'sessions'">Sessions</button>
  <button class="viewnav__btn" :class="{ 'viewnav__btn--on': view === 'workflows' }"
    @click="view = 'workflows'">Workflows</button>
</nav>
...
<main class="stageroot">
  <SessionPanel v-if="view === 'sessions'" />
  <WorkflowPanel v-else />
</main>
```

```css
/* App.vue <style scoped> additions */
.viewnav { display: flex; gap: 4px; margin-left: 22px; }
.viewnav__btn {
  background: transparent; border: 1px solid var(--line); color: var(--text-mid);
  border-radius: 999px; padding: 5px 14px; font-size: 12.5px; cursor: pointer;
  font-family: var(--font-sans);
}
.viewnav__btn--on { color: var(--signal-ink); background: var(--signal); border-color: var(--signal); }
```

Place `<nav class="viewnav">` inside `.topbar`, between `.brand` and `.status` (adjust the topbar to `justify-content: flex-start; gap` as needed, keeping the status pushed right with `margin-left: auto` on `.status`).

- [ ] **Step 3: Type-check, build, and run the frontend suite**

Run (from `frontend/`): `npm run build && npm test`
Expected: build + `vue-tsc` clean; all vitest suites pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/WorkflowPanel.vue frontend/src/App.vue
git commit -m "feat(frontend): add Workflows panel and Sessions/Workflows toggle"
```

---

## Task 12: End-to-end verification (mocked GitHub, local git remote)

**Files:** none (verification only). Uses a mock `claude`, a local bare repo, and a stub GitHub server.

**Interfaces:** exercises the full stack without touching real GitHub.

- [ ] **Step 1: Add a temporary GitHub stub + git remote for manual e2e**

Create `backend/scripts/ghstub.py` (a tiny ASGI app answering `GET issues/{n}`, `GET repos/{repo}`, `PATCH issues/{n}`, `POST pulls`) and a local bare repo under `/tmp`. Run the backend with:

```bash
DISPATCHER_GITHUB_API_BASE=http://localhost:8099 \
DISPATCHER_GIT_BASE=file:///tmp/ghdemo \
DISPATCHER_CLAUDE_BIN=/tmp/mock-claude.py \
DISPATCHER_WORKSPACE_ROOT=/tmp/dispatcher-ws \
uv run uvicorn app.main:app --port 8001
```

- [ ] **Step 2: Drive the UI**

Open the frontend, switch to **Workflows**, start a run against the stub repo/issue, answer the refine question, approve refine → plan → implement, and confirm a PR URL appears. Confirm the branch landed in the local bare repo.

- [ ] **Step 3: Full suites**

Run: `cd backend && uv run pytest -q` and `cd frontend && npm test && npm run build`
Expected: all green.

- [ ] **Step 4: Commit any fixes; remove the throwaway stub if not worth keeping.**

---

## Self-Review

**Spec coverage:**
- Refine (interactive, sentinel write-back) → Task 8 `_refine` + Task 5 helpers + Task 3 `update_issue`. ✓
- Plan / Implement / PR → Task 8 `_plan`/`_implement`/`_drive`. ✓
- Sentinel skip → Task 8 `test_sentinel_skips_refine`. ✓
- Deliverables per step + gates → Task 8 (`deliverable`, `_await_gate`), Task 9 detail, Task 11 UI. ✓
- GitHub via token+API, mocked in tests, configurable base → Task 1, Task 3. ✓
- GitService real-bare-repo test → Task 4. ✓
- Reuse session SSE for live view → Task 10 `watchSession` on `current_session_id`. ✓
- In-memory registry → Task 6. ✓
- Endpoints (create/list/detail/reply/approve/reject), 404/409 → Task 9. ✓
- Config/secrets/.env.example, token not in `.git/config` → Task 1, Task 4 `_auth`. ✓
- Frontend Workflows surface + toggle → Tasks 10–11. ✓

**Placeholder scan:** none — every step carries real code/commands.

**Type consistency:** `run_blocking(prompt, cwd, permission_mode, resume_id, on_session_id)` used identically in Task 7 def and Task 8 fake/calls; `WorkflowStep`/`WorkflowRun` fields match across models (Task 6), service (Task 8), schemas/router (Task 9), and TS types (Task 10); `create_pull_request` signature matches between Task 3 and Task 8's fake.

**Known implementer watch-outs (called out inline):** construct `_Control` via `_new_control()` (loop-bound future), not the bare dataclass default; register the workflow exception handlers in `create_app` (not module scope).
