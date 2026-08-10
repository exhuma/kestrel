"""Shared pytest configuration."""
from __future__ import annotations

import asyncio
import json

import pytest

from app.backends.base import Capability, TurnResult
from app.config import Settings, get_settings
from app.models import CanonicalEvent, EventKind, SessionRecord
from app.services.github import Issue
from app.services.workflows import WorkflowService
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry


@pytest.fixture(autouse=True)
def _ignore_developer_dotenv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep tests hermetic: never read a developer's ``backend/.env``.

    Without this, any ``Settings()`` built in a test would load the local
    ``.env`` (e.g. one pointing the default session backend at a custom
    LLM), silently changing test behavior. Tests that need specific config
    still pass it explicitly.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---- shared doubles/builders for the app.services.workflows test suite ----
# Used across tests/test_workflow_{service,driver,gate,interview,sessions}.py
# — centralised here so each file imports the same fakes rather than
# redefining them.


class _FakeGit:
    """A git double that simulates just enough commit-history state for the
    round-based ``head_sha``/``diff(ref=...)`` semantics in
    ``_code_and_verify`` (feature 006, Phase C).

    Configure rounds via ``self.rounds``: a list of ``(diff_text,
    coder_self_commits)`` pairs, one per coder round. ``head_sha()`` is
    called exactly once per round, always as the first git call of that
    round — the natural hook this fake uses to advance to the next
    configured round, committing it immediately when ``coder_self_commits``
    is True, else leaving it "pending" (uncommitted) until the workflow's
    own safety-net ``commit_all`` (or a test) commits it.

    Synthetic SHAs are ``f"sha{n}"`` where ``n`` is the number of commits
    made so far. ``diff(ref=...)`` recognises that pattern; any other ref
    (e.g. a real base-branch name like ``"main"``) falls back to "from the
    very beginning" (index 0) — the fake never needs to model real branch
    names precisely.

    ``self.diffs`` is kept as a backward-compatible alias over
    ``self.rounds`` for the ~90 existing call sites that do
    ``git.diffs = ["some diff"]`` — plain string assignment always means
    "coder does not self-commit", preserving prior test semantics exactly.
    """

    def __init__(self) -> None:
        self.pushed: list[str] = []
        self.deleted_local: list[tuple[str, str]] = []
        self.deleted_remote: list[tuple[str, str, object]] = []
        self.rounds: list[tuple[str, bool]] = [
            ("diff --git a/x b/x", False)
        ]
        self._round_idx = 0
        #: Diff text of each commit made so far, in order (the "committed
        #: history" half of the fake's state).
        self._committed: list[str] = []
        #: Content not yet committed (the "working tree" half).
        self._pending: str = ""
        self.commit_messages: list[str] = []
        self.diff_excludes: list[str | None] = []

    @property
    def diffs(self) -> list[str]:
        """Backward-compatible alias: the configured rounds' diff text."""
        return [diff_text for diff_text, _self_commits in self.rounds]

    @diffs.setter
    def diffs(self, value: list[str]) -> None:
        self.rounds = [(d, False) for d in value]
        self._round_idx = 0

    async def clone(self, remote_url: str, dest: str, cred=None) -> None: ...
    async def checkout_branch(self, dest: str, branch: str) -> None: ...
    async def ensure_mirror(
        self, remote_url: str, mirror_dir: str, cred=None
    ) -> None: ...
    async def add_worktree(
        self, mirror_dir: str, dest: str, base_branch: str, new_branch: str
    ) -> None: ...
    async def remove_worktree(self, mirror_dir: str, dest: str) -> None: ...

    def mark_dirty(self, diff_text: str) -> None:
        """Test hook: leave the working tree "dirty", independent of the
        round machinery — for tests exercising ``_deliver`` directly."""
        self._pending = diff_text

    async def head_sha(self, dest: str) -> str:
        sha = f"sha{len(self._committed)}"
        idx = self._round_idx if self._round_idx < len(self.rounds) else -1
        diff_text, self_commits = self.rounds[idx]
        self._round_idx += 1
        self._pending = diff_text
        if self_commits and diff_text.strip():
            self._committed.append(diff_text)
            self._pending = ""
        return sha

    async def diff(
        self, dest: str, exclude: str | None = None, ref: str | None = None,
    ) -> str:
        self.diff_excludes.append(exclude)
        return self._diff_since(ref)

    async def diff_stat(
        self, dest: str, exclude: str | None = None, ref: str | None = None,
    ) -> str:
        self.diff_excludes.append(exclude)
        content = self._diff_since(ref)
        return f"{len(content.splitlines())} lines changed" if content else ""

    def _diff_since(self, ref: str | None) -> str:
        if ref is None:
            return self._pending
        parts = [d for d in self._committed[self._sha_index(ref):] if d]
        if self._pending:
            parts.append(self._pending)
        return "\n".join(parts)

    @staticmethod
    def _sha_index(ref: str) -> int:
        if ref.startswith("sha") and ref[3:].isdigit():
            return int(ref[3:])
        return 0  # an unrecognised ref (e.g. a real base-branch name)

    async def commit_all(self, dest: str, message: str) -> None:
        self.commit_messages.append(message)
        if self._pending:
            self._committed.append(self._pending)
            self._pending = ""

    async def push(self, dest: str, branch: str, cred=None) -> None:
        self.pushed.append(branch)

    async def delete_local_branch(self, mirror_dir: str, branch: str) -> None:
        self.deleted_local.append((mirror_dir, branch))

    async def delete_remote_branch(
        self, mirror_dir: str, branch: str, cred=None
    ) -> None:
        self.deleted_remote.append((mirror_dir, branch, cred))


class _FakeNotifier:
    """Records attention-worthy statuses, mirroring the filtering
    every real Notifier implementation is responsible for (see
    InAppNotifier._is_notifiable) rather than recording every
    call unconditionally."""

    def __init__(self) -> None:
        self.notified: list[str] = []

    def notify(self, run) -> None:
        if run.status in ("done", "failed", "escalated") or (
            run.status.startswith("awaiting_")
        ):
            self.notified.append(run.status)


class _FakeGitHub:
    def __init__(self, body: str = "Please add a widget") -> None:
        self.body = body
        self.updated: str | None = None
        self.token = "fake-gh-token"  # read by GitHubCodeHost.git_credential

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
    """A fake backend (canned result per turn) that is also its own policy.

    Doubles as the ``BackendPolicy`` the WorkflowService now depends on:
    every step resolves to this one backend.
    """

    caps = frozenset({Capability.TEXT, Capability.FILE_EDITS})

    def __init__(
        self,
        sessions: SessionRegistry,
        outputs: list[str],
        id_prefix: str = "s",
    ) -> None:
        self.sessions = sessions
        self._outputs = list(outputs)
        self._id_prefix = id_prefix
        self._n = 0
        self.calls: list[dict] = []
        self.terminated: list[str] = []

    async def run_turn(self, req, on_session_id=None):
        sid = req.resume_id or f"{self._id_prefix}{self._n}"
        self._n += 1
        self.calls.append(
            {"resume_id": req.resume_id, "model": req.model,
             "permission_mode": req.permission_mode,
             "prompt": req.prompt}
        )
        text = self._outputs.pop(0)
        if self.sessions.get(sid) is None:
            self.sessions._records[sid] = SessionRecord(
                session_id=sid, cwd=req.cwd
            )
        rec = self.sessions.get(sid)
        rec.events.append(
            CanonicalEvent(EventKind.RESULT, sid, text=text)
        )
        rec.status = "idle"
        if on_session_id:
            on_session_id(sid)
        return TurnResult(session_id=sid, final_text=text)

    def terminate(self, session_id: str) -> bool:
        self.terminated.append(session_id)
        return True

    # -- BackendPolicy interface (every step uses this backend) --
    def backend_for(self, step: str):
        return self

    def backend_id_for(self, step: str) -> str:
        return "fake"

    def backends(self):
        return [self]

    def optional_backend_for(self, step, requirement):
        # No mockup capture in the default harness; the dedicated
        # test_workflow_mockups covers the capable/gated paths.
        return None


class _RoutingPolicy:
    """A BackendPolicy stub routing ``design`` and ``code`` to different
    backends, so a cross-backend session handoff can be exercised.

    Mirrors the real routing where ``design`` may resolve to a TEXT-only
    LLM backend (``llm-…`` session ids) while ``code`` resolves to
    opencode (``ses-…`` ids). Every other step uses the code backend.
    """

    def __init__(
        self, sessions: SessionRegistry, design, code
    ) -> None:
        self.sessions = sessions
        self._design = design
        self._code = code

    def backend_for(self, step: str):
        return self._design if step.split(".", 1)[0] == "design" else (
            self._code
        )

    def backend_id_for(self, step: str) -> str:
        return "llm" if step.split(".", 1)[0] == "design" else "opencode"

    def backends(self):
        return [self._design, self._code]

    def optional_backend_for(self, step, requirement):
        return None


def _service(github, runner, git, settings=None) -> WorkflowService:
    return WorkflowService(
        settings=settings or Settings(
            git_base="https://github.com", github_token="t"
        ),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=git,
        github=github,
        notifier=_FakeNotifier(),
    )


def _settings(**overrides) -> Settings:
    """Test settings with the refinement knobs open to overrides."""
    return Settings(
        git_base="https://github.com", github_token="t", **overrides
    )


def _artifact_service(tmp_path, policy, github=None):
    return _service(
        github or _FakeGitHub(body="vague issue"),
        policy,
        _FakeGit(),
        settings=_settings(workspace_root=str(tmp_path)),
    )


def _coverage(**flags: bool) -> str:
    """A completeness-critic COVERAGE block, one flag per audience."""
    audiences = [
        {"audience": a, "covered": c} for a, c in flags.items()
    ]
    return f"<COVERAGE>{json.dumps({'audiences': audiences})}</COVERAGE>"


def _coord(ids: list[str]) -> str:
    """A coordinator PROFILES block naming the profiles to interview."""
    return f"<PROFILES>{json.dumps(ids)}</PROFILES>"


def _q(qid="q1", prompt="Which auth?", qtype="single_select",
       required=True, options=None, waiver_label=None,
       audience=None, folded_from=None) -> dict:
    """One question dict for a QUESTIONS block.

    ``audience`` and ``folded_from`` are set only on reconciler output,
    where each consolidated question names the profile that owns it and
    the pool ids it absorbed.
    """
    q: dict = {"id": qid, "prompt": prompt, "type": qtype,
               "required": required}
    if options is not None:
        q["options"] = options
    if waiver_label is not None:
        q["waiver_label"] = waiver_label
    if audience is not None:
        q["audience"] = audience
    if folded_from is not None:
        q["folded_from"] = folded_from
    return q


def _qs(*questions: dict) -> str:
    """A generator QUESTIONS block wrapping the given questions."""
    body = json.dumps({"questions": list(questions)})
    return f"<QUESTIONS>{body}</QUESTIONS>"


def _refined(text: str) -> str:
    """A writer REFINED_ISSUE block."""
    return f"<REFINED_ISSUE>\n{text}\n</REFINED_ISSUE>"


def _verdict(
    accept: bool = True,
    feedback: str = "",
    observations: list[dict] | None = None,
) -> str:
    """A verifier VERDICT block (feature 003 autonomous loop).

    ``observations`` optionally carries self-reported http/ui findings
    (feature 005) — a list of ``{name, kind, passed, detail}`` dicts.
    """
    payload: dict = {"accept": accept, "feedback": feedback}
    if observations is not None:
        payload["observations"] = observations
    return f"<VERDICT>{json.dumps(payload)}</VERDICT>"


#: Simplest refine leg: coordinator needs nobody, writer emits the issue.
def _refine_noquestions(text: str) -> list[str]:
    return [_coord([]), _refined(text)]


async def _wait(pred, timeout=2.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached")


class _FakeDismissals:
    """In-memory dismissal store for abandon tests (keyed by task_ref)."""

    def __init__(self) -> None:
        self.added: list[str] = []

    def add(self, task_ref: str) -> None:
        self.added.append(task_ref)

    def is_dismissed(self, task_ref: str) -> bool:
        return task_ref in self.added

    def all(self) -> list[str]:
        return list(self.added)

    def clear(self, task_ref: str) -> None:
        self.added = [p for p in self.added if p != task_ref]


def _write_fixture_task(fixtures_dir, slug: str, **fields) -> None:
    """Write one fixture-source task file (feature 008), for
    FixtureTaskSource/FixturePollService tests."""
    data = {
        "title": "Add a hello endpoint",
        "body": "Add GET /hello.",
        "code_repo": "me/sandbox",
        "base_branch": None,
    }
    data.update(fields)
    (fixtures_dir / f"{slug}.json").write_text(json.dumps(data))
