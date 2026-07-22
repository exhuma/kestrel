# Research: Jira Ingestion & Autonomous Design/Code/Verify Loop

Each entry: **Decision / Rationale / Alternatives**, grounded in the current code
(`file:line` where it anchors) and traced to spec FRs.

## R-01 — Task Source / Code Host port extraction

**Decision**: Introduce `backend/app/ports.py` with two `Protocol`s and a `Task` dataclass:

- `Task`: `ref: str`, `title: str`, `body: str` (source-native ticket ref + text).
- `TaskSource` (keyed by an opaque `ref: str`): `get_task(ref) -> Task`,
  `post_comment(ref, body) -> str`, `attach(ref, name, content) -> None`,
  `publish_refined(ref, content) -> None`, `list_open(...) -> list[Task]` (poll),
  `deep_link_ref(ref) -> str` (source-native URL to the ticket, optional).
- `CodeHost` (keyed by `repo: str`): `get_default_branch(repo) -> str`,
  `open_change_request(repo, *, head, base, title, body, draft=True) -> str`,
  `clone_remote(repo) -> str` (the git remote URL the worktree provisions from).

Split `services/github.py`'s `GitHubClient` behind `GitHubTaskSource` (wraps `get_issue`,
`create_issue_comment`, `list_issues_by_label`, `update_issue`) and `GitHubCodeHost` (wraps
`get_default_branch`, `create_pull_request`, and the `git_base/repo.git` remote today built
inline at `services/workflows.py:681`). `GitHubClient`'s HTTP calls are unchanged.

**Rationale**: `GitHubClient` already cleanly divides into ticket ops and repo ops (see the
Explore split). Ports let `WorkflowService` and the notifier depend on *roles*, not GitHub,
so Jira slots in by implementing `TaskSource` only. This is the "extract with the second
source" decision recorded in feature 002 (`002-github-ingestion/spec.md:417-432`,
`docs/architecture.md:58-66`) — now justified because two concrete sources exist
(Constitution IV). Traces FR-022, FR-023.

**Alternatives**: Branch on `run.source` inside the workflow (rejected — scatters
`if source == …` through `_drive`/`_deliver`/notifier, the coupling 002 warned against). A
plugin/entry-point registry (rejected — YAGNI for two sources wired in one factory).

## R-02 — Jira client & authentication

**Decision**: New `services/jira.py::JiraClient` built on `httpx` (no new dependency —
`GitHubClient` already uses it). Methods: `search(jql, *, fields, max_results) -> list[Task]`
(REST `GET /rest/api/3/search` / `/search/jql`), `get_issue(key) -> Task`,
`add_comment(key, body) -> str`, `add_attachment(key, name, content) -> None`
(`POST /rest/api/3/issue/{key}/attachments`, header `X-Atlassian-Token: no-check`),
`get_field(key, field) -> str | None` (read the repo-resolution field).
Auth is configurable: `basic` (Jira Cloud — HTTP Basic `email:api_token`) or `bearer`
(Jira Server/DC — PAT `Authorization: Bearer …`), selected by `KESTREL_JIRA_AUTH`. The token
is a secret, never logged (FR-004, FR-009 privacy).

**Rationale**: Mirrors `GitHubClient`'s shape so tests mock the same `httpx` transport
(Constitution III). Supporting both auth modes keeps kestrel agnostic of whether the instance
is Cloud or Server (FR-005). Jira comment/attachment bodies are fixed templates + the PRD file
— never model content (FR-029).

**Alternatives**: The `jira` PyPI SDK (rejected — a new dependency for a handful of REST calls,
against Constitution IV). OAuth 2.0 / Connect app (rejected — heavyweight for a single-user
tool; API-token/PAT is the documented personal-automation path).

## R-03 — Code host is operator-configured and self-hostable (GitHub + self-hosted git)

**Decision**: The `CodeHost` used for a Jira-resolved repo is **operator-configured** and ships
**two** first-class implementations: `GitHubCodeHost` (pull request, existing
`create_pull_request`) and `GitLabCodeHost` (`services/gitlab.py`, a **self-hosted GitLab**
merge request via `POST /projects/:id/merge_requests`, draft MRs with a `Draft:` title). A
`KESTREL_CODE_HOST` setting (`github` | `gitlab` | `gitea`) plus a code-host base URL and token
select it; `gitlab` points at a self-hosted instance. GitHub-sourced and manual runs keep using
`GitHubCodeHost` (their code is on GitHub); Jira runs use the configured code host. Gitea/Forgejo
is the same port with different endpoints, added when needed. "Merge request" / "pull request"
are the same concept per host.

**Rationale**: kestrel is **sovereign by design** — meant to run inside an org that values
independence/infosec, self-hosted, no mandatory external cloud. That target runs code on a
self-hosted GitLab/Gitea, so a GitHub.com-only code host would make the feature unusable for the
actual customer. Two concrete `CodeHost` implementations are also what justify the port at all
(a single-impl abstraction is a Constitution IV smell). Reuses `httpx`; no new dependency.
Traces FR-006, FR-019, FR-023, FR-023a.

**Alternatives**: GitHub.com-only with GitLab deferred (rejected — backwards for the sovereignty
target; it makes the port single-impl). Ship Gitea/Forgejo instead of GitLab as the reference
(viable — same port; GitLab chosen for the richest REST MR API and prevalence in regulated orgs;
swap if the deployment runs Gitea/Forgejo). Per-repo host encoded in the Jira field (rejected —
one configured code host instance suffices for a single-org deployment; keeps the field to a
plain repo path).

## R-04 — Source-neutral ticket identity (`task_ref`)

**Decision**: Add `WorkflowRun.task_ref: str` — the source-native ticket id: GitHub
`"owner/name#123"`, Jira the issue key `"RFC-123"`. It becomes the universal key for
ingestion dedup, one-run-per-ticket, dismissal, and notification rendering. `WorkflowRun.repo`
keeps its meaning as the **code repository** (equal to the ticket's repo for GitHub; the
resolved repo for Jira), so worktree/PR paths (`services/workflows.py:681`, `1563`) are
unchanged. `issue_number` becomes GitHub-only and **nullable** (Jira has none).

**Rationale**: The notifier renders `{repo}#{issue_number}` today
(`notifications.py:47-66,84`) and the dismissal store keys on `(repo, issue_number)`
(`tables.py:110-121`) — both GitHub-shaped. One `task_ref` generalizes all of them with the
least churn while leaving the code-repo columns (which already drive git/PR) untouched.
Traces FR-024, FR-031, FR-033.

**Alternatives**: Fake `issue_number=0` for Jira (rejected — leaks GitHub shape, risks
dismissal-PK collisions). A separate Jira dismissal table (rejected — duplicates the guard,
desyncs the two paths).

## R-05 — Unified workflow reshape (`refine → PRD → design → code → verify`)

**Decision**: Reshape `services/workflows.py`. Steps become `["refine", "design", "code",
"verify"]` (rename `plan`→`design`, `implement`→`code`; add `verify`). Run statuses become:
`pending`, `cloning`, `refining`, `awaiting_refine_input`, `awaiting_refine_approval`,
`designing`, `coding`, `verifying`, `opening_pr`, `done`, `failed`, `rejected`, **`escalated`**.
Removed: `planning`, `awaiting_plan_approval`, `implementing`, `awaiting_implement_input`,
`awaiting_implement_approval`. The **only** gates are `awaiting_refine_input` (clarification)
and `awaiting_refine_approval` (**PRD approval**); design/code/verify are gateless for every
source (FR-014, FR-024). `_drive`/`_continue` become source-neutral by resolving the run's
`TaskSource`/`CodeHost` from `run.source` instead of using `self.github` directly. Prompts
`PLAN_PROMPT`→`DESIGN_PROMPT`, `IMPLEMENT_PROMPT`→`CODE_PROMPT`; add `VERIFY_PROMPT` and reuse
the feedback-prompt pattern for the coder re-run.

**Rationale**: The requester chose one predictable workflow across sources — the task source is
only the human↔agent boundary (spec US4; Clarifications 2026-07-21). Reusing the existing
gate/park machinery (`_await_gate`, `_Control`, `_save` at `services/workflows.py:350,628`)
keeps the change surgical: gateless phases simply don't set an `awaiting_*` status. Step names
are free-form persisted strings (`tables.py:79`), so historical `plan`/`implement` rows need no
migration. Traces FR-014, FR-024, FR-025.

**Alternatives**: A separate Jira-only workflow (rejected by the requester — forking breaks
predictability). Keep `plan`/`implement` internal names and only add `verify` (rejected — the
UI renders step names; design/code/verify is the intended, visible vocabulary).

## R-06 — The verifier, behavioural evidence & the bounded loop

**Assumed verification model** (design-level; exact harness deferred per the requester): the
verifier **runs the modified project in the isolated worktree and exercises its real boundary**,
then adjudicates the observed behaviour against the PRD. Initial supported boundaries (FR-015b):

- **HTTP API** (e.g. FastAPI) — launch the app, issue **real HTTP requests**, assert on responses.
- **Web GUI** (e.g. a Vite app) — launch the dev/preview server, **drive it with Playwright** and
  visually inspect (screenshots).

Other boundaries are edge cases that fall back to configured checks / model judgment. The
observations form the evidence; the verifier's job is to **adjudicate behaviour vs the PRD**, not
to guess correctness from the diff.

**Decision (this feature)**: Model the evidence generically so the assumed harness slots in
without reshaping. In `ports.py`: `Observation(name: str, kind: Literal["http","ui","check"],
passed: bool, detail: str)` and `Evidence(observations: list[Observation])`. An **evidence
gatherer** produces `Evidence` before the verifier runs; `verify` passes `VERIFY_PROMPT` = PRD +
design + diff + **evidence** to the `verifier` agent (`backend_for("verify")`, worktree cwd),
which emits `<VERDICT>{ "accept": bool, "feedback": str }</VERDICT>`. **Invariant**: any failing
`Observation` MUST NOT yield `accept`. On accept → `_deliver`; on reject with `i <
max_verify_iterations` → re-run `code` with feedback **including the failing observations**,
increment `i`, re-verify; on exhaustion → `escalated` + comment + teardown. The iteration counter
and evidence are **in-memory** on `_Control`; a restart during `coding`/`verifying`/`designing`
fails loudly via `_TRANSIENT`. `max_verify_iterations` defaults to 3.

**v1 concrete scope**: ship the `Observation`/`Evidence` interface, the verifier-as-adjudicator
role, the invariant, and a **minimal interim gatherer** — `services/checks.py::CheckRunner`
running the operator-configured `verify_checks` commands in the worktree (emitting `kind="check"`
observations). The **behavioural harness** — launching the app, HTTP-exercising an API, Playwright
driving a GUI, and boundary detection (emitting `kind="http"`/`"ui"` observations) — is
**designed-for but deferred** (delivered incrementally); the interface already carries its output.
When no gatherer produces observations, verification falls back to model judgment (empty
`Evidence`, interface still carried).

**Rationale**: An LLM judging its sibling's diff unaided is a weak, ungrounded signal — the risk
the requester wants closed, and sharper under sovereignty (a weaker on-prem model's unaided
judgment is trusted less). Grounding the verdict in the project's **actual runtime behaviour** at
its real boundary (not just "the test suite passed") is the strongest available signal and matches
how RFC changes materialise — new API behaviour or new UI behaviour. Generalising `Observation`
with a `kind` now is the cheap forward-compat move: the deferred HTTP/Playwright harness adds
`http`/`ui` observations without touching the workflow. Traces FR-015, FR-015a, FR-015b, FR-016,
FR-017, FR-018, FR-020, SC-006a.

**Alternatives**: LLM-judgment-only verifier (rejected — ships plausible-but-wrong work, the
risk the requester wants closed). Making the gatherer the *sole* gate with no LLM
(rejected — checks can't judge "did it satisfy the PRD's intent", only "did the suite pass"; the
LLM adjudicates the gap, and many repos lack full coverage). Emitting structured acceptance
criteria from refinement now (deferred — the stated future work; v1 ships the evidence interface
+ a minimal runner). Wall-clock/token budget bound (rejected earlier by the requester in favour
of an iteration count). Persisting the counter to resume mid-loop (rejected — no other transient
state resumes).

## R-07 — PRD delivery: attachment + thin notification

**Decision**: On PRD approval, `TaskSource.publish_refined(ref, prd)` records the approved PRD
on the ticket: `GitHubTaskSource` keeps today's behaviour (`update_issue` with the refined body
+ sentinel, `services/workflows.py:752`); `JiraTaskSource` calls `add_attachment(key,
"PRD.md", prd)` (FR-011). Separately, the notifier posts a **thin** comment (status +
deep-link only) for each gate and boundary event (FR-029). Clarification notifications
likewise carry only a deep-link to the existing questionnaire — never the questions (US2).

**Rationale**: Keeps internal content behind the UI regardless of ticket visibility, reusing
the fixed-template discipline already proven for GitHub gate comments
(`notifications.py:47-66,152`). The PRD as an attachment matches "attach the final PRD"
(spec US2) without dumping it into a comment. Traces FR-011, FR-013, FR-029.

**Alternatives**: Inline the PRD in a comment (rejected — violates the thin-notification /
no-content rule and floods a possibly-public ticket).

## R-08 — Source-dispatching notifier

**Decision**: Replace `GitHubIssueNotifier` with `TaskSourceNotifier(sources: dict[str,
TaskSource], public_base_url)`. On `notify(run)` for an `awaiting_*` gate (and the new
boundary events), it resolves `sources[run.source]`, renders the fixed template using
`run.task_ref`, appends the deep-link, and posts via `post_comment` in a fire-and-forget task
(unchanged best-effort semantics, `notifications.py:169-196`). `render_message` switches its
`{repo}#{issue_number}` placeholder to a single `{task}` fed by `run.task_ref` so it is
source-neutral. `InAppNotifier` stays first in the `CompositeNotifier` as the durable fallback
(`services/workflows.py:1587-1594`).

**Rationale**: A run's comment must reach *its* ticket via *its* source; one dispatcher keyed
on `run.source` centralizes the thin-content and best-effort rules (FR-028, FR-029) instead of
N per-source notifiers each re-checking the discriminator. Traces FR-027, FR-028.

**Alternatives**: One notifier per source composed together, each no-op on the wrong source
(rejected — redundant fan-out, duplicated guards).

## R-09 — Repository resolution from a configurable field

**Decision**: `KESTREL_JIRA_REPO_FIELD` names the Jira field (id like `customfield_10050` or a
name resolved to an id) holding the target `owner/name` (optionally `owner/name@base_branch`).
On ingest, `JiraTaskSource.get_field(key, repo_field)` yields the value; the poll service
validates it names a resolvable, reachable GitHub repo (via `CodeHost.get_default_branch`
probe) before starting a run. An empty/malformed/unreachable value → **no run**, an
`unresolved-repo` log outcome, and a thin comment on the RFC that the target repo could not be
determined (FR-007). A missing field on the Jira schema is surfaced as an operator
misconfiguration in logs (FR-008).

**Rationale**: The requester chose a configurable field, keeping kestrel agnostic of
company-internal Jira conventions (FR-005, FR-006). Probing the repo before starting avoids
half-started runs that fail at worktree time. Traces FR-006, FR-007, FR-008.

**Alternatives**: Infer the repo from project/component conventions (rejected — company-internal,
not agnostic). A kestrel-side project→repo config map (offered earlier; the requester chose the
ticket field — the field is per-ticket and needs no redeploy to retarget).

## R-10 — Jira poll loop & source-neutral ingestion entry point

**Decision**: `services/jira_poll.py::JiraPollService.run_forever()` mirrors
`ReconcileService.run_forever()` (`services/reconcile.py:66`): a cycle runs immediately then
sleeps `KESTREL_JIRA_POLL_INTERVAL_SECONDS`. A cycle searches the qualifying JQL (`project =
"{jira_project}"` plus optional `KESTREL_JIRA_JQL_FILTER`), resolves each RFC's repo (R-09),
and calls the **generalized** `IngestionService.maybe_start_run(*, source="jira-issue",
task_ref=key, code_repo, base_branch, title)`. `maybe_start_run` (`services/ingestion.py:43`)
is generalized from `(repo, issue_number, source)` to a source-neutral signature that keys
dedup/dismissal/one-run on `task_ref`. It stays the single choke point both the Jira poll and
the existing GitHub webhook+reconcile call (FR-031, FR-034). The poll task is started in the
lifespan (`main.py:63-77`) when `jira_base_url` and `jira_project` are set, cancelled on
shutdown, exactly like the GitHub reconciler.

**Rationale**: Reuses the proven reconcile shape and the existing ingestion guard, so the Jira
path is thin and idempotency/restart-safety come for free (FR-031, FR-032). A single
source-neutral entry point makes a future Jira webhook one added caller (FR-034). Traces
FR-001, FR-002, FR-003, FR-031, FR-034.

**Alternatives**: A separate Jira ingestion guard (rejected — duplicates the one-run/dismissal
logic). A generic scheduler abstraction over both loops (rejected — two bare asyncio tasks in
the lifespan is the existing, sufficient pattern; Constitution IV).

## R-11 — Configuration surface

**Decision**: Add to `Settings` (`config.py`, prefix `KESTREL_`): `jira_base_url`,
`jira_auth` (`basic`|`bearer`, default `basic`), `jira_email`, `jira_api_token` (secret),
`jira_project`, `jira_jql_filter` (default `""`), `jira_repo_field`,
`jira_poll_interval_seconds` (default 300); the code-host selector `code_host`
(`github`|`gitlab`|`gitea`, default `github`), `code_host_base_url` (self-hosted instance URL),
`code_host_token` (secret; falls back to `github_token` when `code_host="github"`); the verify
grounding `verify_checks: list[str]` (default `[]` — shell commands run in the worktree) and
the source-neutral `max_verify_iterations` (default 3). Reuse `public_base_url`, `git_base`,
`github_token`. Add `model_validator` warnings when `jira_base_url` is set without
`jira_project`/`jira_api_token`, and when `code_host` is a self-hosted type without
`code_host_base_url`/`code_host_token` (mirrors the existing `watched_repos`/`webhook_secret`
warning, `config.py:215-228`). `.env.example` documents every key; tokens stay out of version
control (Constitution V).

**Rationale**: One flexible JQL filter keeps kestrel agnostic of company workflow states
(FR-005). Warning-not-failing on partial config matches the existing ingestion posture
(silent no-op is the worse failure). Traces FR-002, FR-036.

**Alternatives**: Discrete `jira_status`/`jira_trigger_label` settings (rejected — less
flexible than raw JQL and still company-specific). A full config file for Jira (rejected — env
+ the file-only backends pattern already cover the project's config needs).

## R-12 — Frontend: new statuses & step names

**Decision**: Extend the frontend status/step label + chip-tone maps to render `designing`,
`coding`, `verifying`, `escalated`, and step names `design`/`code`/`verify`, using existing
Vuetify theme tokens (no hard-coded colours, Constitution V). `escalated` renders as an
attention/terminal tone with the deep-link already carried by the run. No new frontend
**type** is added and `source` is not surfaced (FR-026); this is an enum-value extension of the
already-synced `WorkflowDetail` shape (Constitution I). vitest covers the new mappings.

**Rationale**: The reshaped workflow is visible in the run detail; the frontend must name the
new phases and the escalation outcome. Keeping the change to label/tone maps honours the
backend-owned-logic rule (the frontend only renders). Traces FR-024, FR-026, Constitution I/V.

**Alternatives**: Show raw status strings (rejected — inconsistent with the existing curated
labels). Add `source` to drive per-source UI (rejected — FR-026 forbids it; the UI is uniform).

## R-13 — Restart & idempotency (reuse)

**Decision**: No new recovery machinery. `recover()` (`services/workflows.py:634`) already
re-parks `awaiting_*` runs and fails `_TRANSIENT` runs; the new `designing`/`coding`/`verifying`
join `_TRANSIENT`, and `escalated`/`done`/`failed`/`rejected` are terminal. Ingestion dedup and
dismissal (now keyed on `task_ref`) give one-run-per-RFC across cycles and restarts (FR-031,
FR-032, FR-033). Gate-comment restart idempotency is inherited: recovery re-parks without
calling `_save`, so the notifier does not re-fire (feature 002 R-07 pattern).

**Rationale**: The transient-fail-on-restart contract already covers the autonomous loop; the
verifier loop is just more transient work. Traces FR-031, FR-032.

**Alternatives**: Persist and resume the in-flight loop (rejected — inconsistent with every
other transient state; see R-06).
