<!--
SYNC IMPACT REPORT
==================
Amendment 2026-10-05 (1.5.1 -> 1.6.0, MINOR): Add Principle VI, "Documents
Are Modelled, Never Strings" (NON-NEGOTIABLE). Every document kestrel handles
is the abstract `Document` internally; parsing and rendering happen only in
the adapter at a system boundary (task sources, code hosts, agent backends,
persistence, the HTTP API), never in core code, and never as a format
round-trip inside an adapter. Prompted by the Jira-first alpha: Jira Cloud
requires ADF, and string-typed documents leak platform syntax into the core.
Existing violations are named as debt.
The same amendment records a fourth access-model constraint: kestrel never
changes the status of an ingested task, only of sub-tasks it created itself;
it asks the responsible human in a comment instead. Feature 006's
`TaskSource.transition` port and `transition_*` settings remain, restricted
to kestrel-created sub-tasks (nothing calls them today). A new principle and
a new constraint, therefore MINOR.

Added sections:
  - Core Principles -> VI. Documents Are Modelled, Never Strings
  - Technology & Architecture Constraints -> access model: fourth recorded
    constraint (no status changes on an ingested task)

Templates & docs reviewed for consistency:
  - .specify/templates/plan-template.md ...... no edit; gates are derived
    from this file dynamically
  - .specify/templates/spec-template.md ...... no edit; no section changed
  - .specify/templates/tasks-template.md ..... no edit
  - AGENTS.md ................................ consistent; defers to this file

Follow-up TODOs:
  - Add the import-linter contract (only adapters import parse/render).
  - Remove the named violations; the Jira-first alpha plan schedules this.

--------------------------------------------------------------------------------
Amendment 2026-09-24 (1.5.0 -> 1.5.1, PATCH): Correct a factual drift left by
the Phase 10 clean break (spec 026-autonomous-work-board): the fixed six-step
workflow driver and its `/api/workflows/*` router — the sole implementation of
"Kestrel's rerun action" referenced in the access model's third recorded
constraint — were removed. No principle or binding constraint is added,
removed, or redefined: the visibility()-gated restriction on any local-only
destructive action remains binding for if/when such an action is
reintroduced; only the constraint's description is updated to state plainly
that no such action exists in the current board-domain implementation.
Therefore PATCH, per the same class of change as the 1.0.0 -> 1.0.1 amendment
below.

Modified sections:
  - Technology & Architecture Constraints -> access-model third constraint:
    added a note that rerun is not currently implemented, without altering
    the underlying restriction.

Templates & docs reviewed for consistency:
  - docs/architecture.md, docs/configuration.md, docs/setup-local-tasks.md,
    README.md ... updated in the same pass to drop the "Rerun action" as a
    currently offered feature (see those files' own history for detail).

Follow-up TODOs: none.

--------------------------------------------------------------------------------
Amendment 2026-09-15 (1.4.0 -> 1.5.0, MINOR): Permit tightly scoped cleanup
writes for artifacts Kestrel itself created and durably recorded. The prior
public-source constraint made delete/cleanup local-only so externally shared
tickets could never be rewritten. That made a reset incomplete: approved PRDs,
comments, attachments, and generated sub-tasks survived, and the next poll did
not see the original task state. Cleanup may now delete, close, or restore only
a Kestrel-owned artifact with a durable workflow-artifact record; it must never
change the original task beyond restoring its exact pre-publication state.
Missing artifacts are successful cleanup, required failures remain tracked for
retry, and comment/feedback deletion is explicitly best-effort. This is a
material expansion of the public-source write posture, therefore MINOR.

Modified sections:
  - Technology & Architecture Constraints -> access-model third constraint
    expanded with ownership, idempotency, restoration, and failure boundaries.

Templates & docs reviewed for consistency:
  - .specify/templates/plan-template.md ...... no edit; dynamic check
  - .specify/templates/spec-template.md ...... no edit; no section changed
  - .specify/templates/tasks-template.md ..... no edit; tasks can represent it
  - AGENTS.md ................................ consistent; defers constraints
  - docs/architecture.md .................... update during implementation to
    document cleanup artifact ownership and lifecycle.

Follow-up TODOs:
  - Update operator-facing cleanup documentation during implementation.

--------------------------------------------------------------------------------
Amendment 2026-08-10 (1.3.0 → 1.4.0, MINOR): Record the visibility/rerun constraint
introduced by feature 008-fixture-task-source in "Technology & Architecture
Constraints". Every `TaskSource` implementation (`backend/app/ports.py`) now declares
a `visibility()` capability, `"public"` or `"private"`: GitHub and Jira report
`"public"`; the new file-backed fixture source reports `"private"`. Kestrel's rerun
action — the one operation that discards and replaces a run's history — is permitted
only when the run's task source reports `"private"`. Public sources were already never
rewritten or deleted by kestrel (delete/cleanup act only on local state); this
amendment does not change that behavior, it formalizes the guarantee as a binding
constraint and extends it to gate the new rerun action, so a public source can never
be misconfigured into allowing history to be discarded and replaced. MINOR because it
adds a new permitted-deviation-adjacent constraint without redefining or removing any
existing principle. Required by Principle I ("any intentional departure … MUST be
recorded here … before it is relied upon") so feature 008-fixture-task-source's rerun
action can proceed.

Modified sections:
  - Technology & Architecture Constraints → "Access model" bullet expanded with the
    recorded `TaskSource.visibility()` / rerun-gating constraint.

Templates & docs reviewed for consistency:
  - .specify/templates/plan-template.md ...... ✅ aligned (Constitution Check gate
    references the constitution dynamically; no edit)
  - .specify/templates/spec-template.md ...... ✅ aligned (no mandatory section
    changed)
  - .specify/templates/tasks-template.md ..... ✅ aligned (no new principle-driven
    task type)
  - .claude/skills/speckit-*/SKILL.md ........ ✅ reviewed; generic guidance
  - AGENTS.md / docs/next-steps.md ........... ✅ consistent (AGENTS.md defers the
    access model to this file; next-steps unaffected)
  - docs/architecture.md .................... ✅ updated: notes the fixture source
    and the visibility()/rerun axis alongside the existing GitHub/Jira ports
    description (008 implementation, Polish phase).

Follow-up TODOs: none — this amendment's operator-facing guidance (the fixture
`[[task_sources]]` entry) lives entirely in `config.toml.example`, already covered by
008's implementation.

--------------------------------------------------------------------------------
Amendment 2026-07-27 (1.2.0 → 1.3.0, MINOR): Record a deliberate departure for the
new operator-hooks mechanism (feature 006-task-lifecycle-sync) in "Technology &
Architecture Constraints". Kestrel now executes arbitrary operator-provided
executables from a configured, per-task-source `hooks_dir` at defined workflow-run
lifecycle points (run start, done, failed, escalated, rejected); each invocation
inherits kestrel's full process environment, including every configured credential
(GitHub/Jira/code-host tokens), by deliberate design — a hook can call the same
ticket-tracker API kestrel itself uses, with kestrel's own credentials, to perform
custom actions kestrel does not natively support. This makes `hooks_dir` and its
contents a secret-equivalent trust boundary, not merely "the same trust as host
access": an operator who would not let an untrusted party write to their
`config.toml` must not let one write to (or place a file into) a configured
`hooks_dir` either. No sandboxing is implemented beyond per-invocation failure
isolation (a 30-second timeout, and one hook's failure never blocking another hook
or the run) and a startup audit log of each configured `hooks_dir`'s contents (a
nudge, not an access control). MINOR because it materially expands the recorded
Access model constraint with a new permitted deviation and its conditions; no
principle is removed or redefined, and every other route/mechanism keeps its
existing trust posture. Required by Principle I ("any intentional departure … MUST
be recorded here … before it is relied upon") so feature 006-task-lifecycle-sync's
hooks mechanism can proceed.

Modified sections:
  - Technology & Architecture Constraints → "Access model" bullet expanded with the
    recorded operator-hooks deviation, its credential-exposure scope, and its
    mitigations.

Templates & docs reviewed for consistency:
  - .specify/templates/plan-template.md ...... ✅ aligned (Constitution Check gate
    references the constitution dynamically; no edit)
  - .specify/templates/spec-template.md ...... ✅ aligned (no mandatory section
    changed)
  - .specify/templates/tasks-template.md ..... ✅ aligned (no new principle-driven
    task type)
  - .claude/skills/speckit-*/SKILL.md ........ ✅ reviewed; generic guidance
  - AGENTS.md / docs/next-steps.md ........... ✅ consistent (AGENTS.md defers the
    access model to this file; next-steps unaffected)
  - docs/architecture.md .................... ⚠ pending: should note the hooks
    mechanism's credential-exposure trust boundary alongside the existing webhook
    exception; update during 006 implementation to prevent drift.

Follow-up TODOs:
  - docs/hooks.md (new) and docs/setup-jira-workflow.md carry the operator-facing
    warning in full; this amendment records the binding constraint, not the
    step-by-step guidance.

--------------------------------------------------------------------------------
Amendment 2026-07-21 (1.1.0 → 1.2.0, MINOR): Record a deliberate deviation from
the loopback-bound access model in "Technology & Architecture Constraints". The
GitHub webhook ingress endpoint (`POST /api/github/webhook`, feature
002-github-ingestion) is intentionally reachable off-loopback so GitHub can
deliver events; its authenticity gate is HMAC verification of
`X-Hub-Signature-256` against a configured shared secret (constant-time), not
loopback binding. Every other route stays loopback-bound and unauthenticated.
Also records the optional public UI base URL (for notification deep-links) as the
same operator-exposure posture, carrying no secret in the link. MINOR because it
materially expands an existing constraint with a new permitted deviation and its
conditions; no principle is removed or redefined, and the loopback rule still
governs every other endpoint. Required by Principle I ("any intentional departure
… MUST be recorded here … before it is relied upon") so feature
002-github-ingestion can proceed.

Modified sections:
  - Technology & Architecture Constraints → "Access model" bullet expanded with
    the recorded webhook + public-UI deviation and its HMAC authenticity gate.

Templates & docs reviewed for consistency:
  - .specify/templates/plan-template.md ...... ✅ aligned (Constitution Check gate
    references the constitution dynamically; no edit)
  - .specify/templates/spec-template.md ...... ✅ aligned (no mandatory section
    changed)
  - .specify/templates/tasks-template.md ..... ✅ aligned (no new principle-driven
    task type)
  - .claude/skills/speckit-*/SKILL.md ........ ✅ reviewed; generic guidance
  - AGENTS.md / docs/next-steps.md ........... ✅ consistent (next-steps already
    anticipates webhook ingress; AGENTS.md defers the access model to this file)
  - docs/architecture.md .................... ⚠ pending: line ~54 ("tool bound to
    loopback. Multi-user/authn is out of scope.") should note the single
    off-loopback webhook exception; update during 002 implementation to prevent
    drift (it is the system-context source of truth).

Follow-up TODOs:
  - docs/architecture.md and docs/setup-github-workflow.md are updated as part of
    feature 002-github-ingestion implementation (webhook exposure guidance).

--------------------------------------------------------------------------------
Amendment 2026-07-21 (1.0.1 → 1.1.0, MINOR): Fold the standalone repo-level
`contract.md` into this constitution and delete that file. Principle I (Contract
Fidelity) is reworded so THIS document — not an external file — is the
authoritative record of the constraints an agent must honour; the type-contract
rule is retained, and the contract's access model (single-user, unauthenticated,
loopback-bound; shared-secret gate only) is captured in Technology &
Architecture Constraints. No obligation was removed or reversed — the contract's
constraints were already reflected here — which is why this is MINOR rather than
a MAJOR principle redefinition. Dangling references updated in AGENTS.md,
backend/app/schemas.py, docs/qm-alignment.md, and
.specify/specs/000-baseline/spec.md.

Amendment 2026-07-21 (1.0.0 → 1.0.1, PATCH): Link docs/architecture.md as the
authoritative system-context source from "Technology & Architecture Constraints"
(reference, not a copy, to prevent drift). No principle changed.

Version change: (unversioned template) → 1.0.0
Rationale: Initial ratification. The template placeholders are replaced with
concrete, project-derived principles for the first time, so this is a MAJOR
baseline (1.0.0) rather than an amendment.

Modified principles (placeholder → concrete):
  - [PRINCIPLE_1_NAME] → I. Contract Fidelity
  - [PRINCIPLE_2_NAME] → II. Layered, Backend-Owned Architecture
  - [PRINCIPLE_3_NAME] → III. Test-First Discipline (NON-NEGOTIABLE)
  - [PRINCIPLE_4_NAME] → IV. Deliberate Simplicity & Single-User Scope
  - [PRINCIPLE_5_NAME] → V. Kit-Aligned Consistency & Observability

Added sections:
  - Technology & Architecture Constraints (was [SECTION_2_NAME])
  - Development Workflow & Quality Gates (was [SECTION_3_NAME])

Removed sections: none.

Templates & docs reviewed for consistency:
  - .specify/templates/plan-template.md ...... ✅ aligned (Constitution Check
    gate references this file dynamically; no edits required)
  - .specify/templates/spec-template.md ...... ✅ aligned (no mandatory
    section added/removed by this constitution)
  - .specify/templates/tasks-template.md ..... ✅ aligned (test-first and
    quality tasks already representable)
  - .claude/skills/speckit-*/SKILL.md ........ ✅ reviewed; generic guidance,
    no outdated agent-specific references to fix
  - README.md / contract.md / docs/* ......... ✅ consistent; this constitution
    codifies existing contract.md constraints, adds no conflicts

Follow-up TODOs:
  - RATIFICATION_DATE is set to the first-fill date (2026-07-21). If the project
    recognises an earlier formal adoption date, amend it (PATCH bump).
-->

# kestrel Constitution

## Core Principles

### I. Contract Fidelity

This constitution is the authoritative record of the constraints an agent MUST
honour when changing the code. Every change MUST be consistent with it and MUST
NOT silently contradict it; any intentional departure from stack norms MUST be
recorded here (see Technology & Architecture Constraints), with its rationale,
before it is relied upon. The frontend/backend **type contract** MUST stay in
sync: business types in `frontend/src/types/` mirror the backend JSON shapes
they represent (e.g. `SessionSummary`, `SessionEvent`), and changing one side
without the other is prohibited.

**Rationale**: A single, version-controlled record prevents drift between the
backend and frontend and keeps deliberate deviations visible instead of tribal
knowledge.

### II. Layered, Backend-Owned Architecture

All business logic lives in the FastAPI backend (routers → services → stores),
with calls flowing downward only. The Vue/Vuetify frontend performs UX-only
client-side checks and MUST NOT be the sole enforcer of any rule that matters
for correctness or security. The database schema is owned exclusively by
Alembic: `Base.metadata.create_all()` and raw DDL (`CREATE TABLE`,
`ALTER TABLE`, interpolated SQL) in application code are prohibited.

**Rationale**: Keeping authority in the backend makes the system testable and
trustworthy regardless of the client, and Alembic-owned schema keeps migrations
reviewable and reversible.

### III. Test-First Discipline (NON-NEGOTIABLE)

Behaviour changes ship with tests: pytest for the backend, vitest for the
frontend. Tests are written to express the intended behaviour and MUST pass
before merge. Frontend tests MUST mock all HTTP calls; tests MUST NOT run
against a production database or a real `claude` subprocess. A bug fix starts
with a test that reproduces the bug.

**Rationale**: Tests are the executable specification of intended behaviour and
the only durable guard against regressions in a fast-moving alpha.

### IV. Deliberate Simplicity & Single-User Scope

kestrel is single-user by design. YAGNI governs: features, abstractions, and
dependencies are added only when a present need justifies them, and every new
npm/Python dependency MUST be justified. Single-user assumptions (e.g. no
multi-user auth) are intentional and MUST NOT be "fixed" by speculative
generalisation; the only planned access protection is a shared-secret gate, not
multi-user authentication. Added complexity MUST be recorded and justified (see
Governance).

**Rationale**: The project's value comes from being a focused personal tool;
unrequested generality is cost without benefit and erodes the contract.

### V. Kit-Aligned Consistency & Observability

Work follows the Quartermaster instruction kits resolved for the task
(`resolve_kits` per task, per `AGENTS.md`); the stack conventions those kits
encode are the default, and divergence MUST be justified. UI styling is
sourced from the Vuetify theme and design tokens — hard-coded hex/rgb/named CSS
colours are prohibited. The service stays observable: structured logging
(text or JSON) and health endpoints are maintained, and secrets are never
committed (`.env` stays out of version control; `.env.example` is the
documented template).

**Rationale**: Consistency across a two-language codebase and continuous
observability are what let a single maintainer move quickly without breaking
trust in the running system.

### VI. Documents Are Modelled, Never Strings (NON-NEGOTIABLE)

Every document kestrel handles — ticket bodies, comments it reads or posts,
PR/MR bodies and review comments, gate announcements, artifacts such as the
restatement, PRD and executive summary, and agent-authored text — MUST be
modelled internally as the abstract `Document` (`backend/app/documents.py`: a
closed set of inline and block constructs).

- **Parse and render only at a system boundary**, inside that boundary's
  adapter: task sources and code hosts (Jira ADF in and out; GitHub and
  GitLab Markdown in and out), agent backends (agent-authored Markdown is
  parsed when the result is accepted), persistence (Document serialisation)
  and the HTTP API to the frontend.
- **Core and board code MUST NOT** build, concatenate, append to or inspect
  raw Markdown, ADF or wiki-markup strings, and MUST NOT pass `str` where a
  document is meant: ports take `Document`, never `Document | str`.
- **No round-trips inside an adapter.** An adapter renders the `Document` it
  is given straight to its platform format; it MUST NOT render to another
  format and re-parse (e.g. to Markdown, to append a sentinel). Sentinels and
  markers are `Document` constructs.
- **Inbound content stays structured.** An adapter converts what it reads
  into a `Document`; port types do not flatten it to plain text. A consumer
  that needs plain text asks the `Document` for it.
- **Enforced mechanically** where a tool can: an import-linter contract
  allows only adapter modules to import the parse and render functions.

Code that predates this principle and violates it is known debt to remove,
never precedent to copy: the ports' `Document | str` parameters,
`JiraTaskSource.post_comment` rendering to Markdown and re-parsing to append
its sentinel, `Task.body` and `Feedback.body` flattened to plain text, and
board projections posting plain strings.

**Rationale**: Platforms disagree on format — Jira Cloud requires ADF, and
Markdown sent to it is not rendered — so a string-typed document leaks one
platform's syntax into the core and from there into every other platform. One
internal model, converted only at the edge, makes each adapter the single
place that knows its platform.

## Technology & Architecture Constraints

The living description of how the system fits together is
[`docs/architecture.md`](../../docs/architecture.md) — it is the source of truth
for system context and MUST NOT be duplicated here (a copy would drift). This
section records only the non-negotiable constraints an agent must honour.

- **Backend**: FastAPI (Python), managed with `uv`, in `backend/`.
  `pyproject.toml` is the dependency source of truth.
- **Frontend**: Vue 3 + Vuetify 4 + TypeScript (Vite, npm), in `frontend/`.
  `package.json` is the dependency source of truth. Components use the
  Composition API (`<script setup lang="ts">`).
- **Persistence**: SQLite via SQLAlchemy 2.x, schema owned by Alembic
  (`backend/alembic/`). Two deliberate, recorded deviations from the usual
  FastAPI/SQLAlchemy patterns are permitted and MUST be preserved unless this
  constitution is amended: stores own their `Session` lifecycle (a
  `sessionmaker(...).begin()` context per operation; no request-scoped `get_db`
  dependency), and timestamps are stored as naive UTC.
- **Worker agent**: the backend invokes the host's logged-in `claude` CLI as a
  subprocess (OAuth/Max subscription). No `ANTHROPIC_API_KEY` and no Agent SDK.
  Alternative backends (opencode, self-hosted LLM) are dispatched the same way.
- **Access model**: single concurrent user; the API is unauthenticated and bound
  to loopback, with **one recorded exception**: the GitHub webhook ingress
  endpoint (`POST /api/github/webhook`) is intentionally reachable off-loopback so
  GitHub can deliver events. For that endpoint the authenticity gate is HMAC
  verification of each delivery's `X-Hub-Signature-256` against a configured shared
  secret, using a constant-time comparison; a delivery whose signature is missing
  or does not match MUST be rejected and MUST start no work, and the secret and
  signatures MUST never be logged. Every other route stays loopback-bound and
  unauthenticated. How the webhook endpoint is exposed (tunnel, reverse proxy) is
  the operator's responsibility. The only planned protection is a shared-secret
  access gate (see `docs/next-steps.md`), not multi-user authentication; the
  webhook HMAC is that same shared-secret posture applied to the one endpoint that
  must face the network. Optionally, the web UI may be served at a configured
  public base URL so that notification deep-links are clickable; this is the same
  operator-exposure posture and the link MUST carry no secret. **Second recorded
  exception** (feature 006-task-lifecycle-sync): a task source MAY configure a
  `hooks_dir` — a filesystem directory of operator-provided executables invoked at
  workflow-run lifecycle events (start/done/failed/escalated/rejected), git-hook
  style, with the event as JSON on stdin. Every such invocation inherits kestrel's
  full process environment, including every configured credential, by deliberate
  design, so a hook can itself call a ticket tracker's API with kestrel's own
  token. This is **not** merely "the same trust as host access" — it is a
  secret-equivalent trust boundary: `hooks_dir` and everything placed in it MUST be
  treated with the same care as `config.toml`/the secrets it references, and MUST
  be documented as such wherever an operator configures it. No sandboxing is
  implemented; the only mitigations are per-invocation isolation (a hard 30-second
  timeout; one hook's failure, timeout, or malformed output MUST never block
  another configured hook or the run itself) and a startup audit log listing each
  configured `hooks_dir`'s executable contents (flagging any that are
  group/world-writable) so an operator has a chance to notice an unexpected file —
  a nudge, not an access control. **Third recorded constraint** (feature
  008-fixture-task-source): every `TaskSource` implementation (`backend/app/ports.py`)
  declares a `visibility()` capability, `"public"` or `"private"`, static per
  implementation and never configurable per instance. GitHub and Jira report
  `"public"` — their tickets are externally shared and MUST only ever move forward in
  time, the same append-only posture git gives a published branch. The file-backed
  fixture task source (feature 008) reports `"private"` — local, admin-only, and safe
  to reset. Kestrel's rerun action — abandon a run, force-delete its branch, and
  immediately restart it against the same task, discarding and replacing the run's
  history — MUST be refused unless the run's task source reports `"private"`; this is
enforced once, centrally, in the service layer (never left to the frontend to
enforce alone, per Principle II). **Not currently implemented**: the fixed
driver's `/api/workflows/*` router, the sole implementation of rerun, was
removed in the Phase 10 clean break (spec 026-autonomous-work-board);
`visibility()` is still recorded on every board workflow, and this same
visibility-gated restriction and central-enforcement requirement apply
unchanged if rerun, or an equivalent local-only destructive action, is
reintroduced. Delete remains local-only. Cleanup may modify
a public source solely to remove, close, or restore artifacts Kestrel itself
created and recorded against that workflow; it MUST NOT alter an untracked
resource or change the original source task except to restore its exact
pre-publication state. Artifact cleanup MUST be idempotent: an absent artifact
is success, while an unresolved required cleanup failure remains recorded for
retry. Deleting comments/feedback is best-effort and cannot prevent the local
reset or future polling eligibility. **Fourth recorded constraint**: kestrel
MUST NOT change the status (workflow state, transition, resolution) of an
ingested task — the ticket a request was ingested from belongs to its owners,
and moving it is their decision. Kestrel MAY transition only sub-tasks it
created itself and recorded against the workflow. Where an ingested task
should move on, kestrel tells the responsible human in a comment instead.
Operator-provided `hooks_dir` executables are the operator's own code and
outside this constraint, but kestrel itself MUST NOT call
`TaskSource.transition` on an ingested task.
- **Run modes**: a bundled Docker image (backend + built SPA + `claude` CLI)
  and a run-from-source developer flow (uv / vite) MUST both remain working.

## Development Workflow & Quality Gates

- **Kit resolution**: call `resolve_kits(task="…")` at the start of each task
  and whenever the task's direction shifts, then pull sections on demand. Do
  not hard-code a fixed kit list.
- **Quality gates before merge**: backend and frontend test suites pass;
  linters/formatters pass with no suppressions added to dodge a real finding.
- **Documentation**: user-facing or behavioural changes update the relevant
  docs (`README.md`, `docs/*`) and, when binding constraints change, this
  constitution.
- **Security-first, minimal changes**: prefer the smallest change that solves
  the problem; ask before guessing at ambiguous requirements; never introduce
  hard-coded secrets or credentials.
- **Releases**: versioning follows CalVer with the channels documented in
  `docs/releasing.md`.

## Governance

This constitution supersedes ad-hoc practice for the topics it covers and is the
single authoritative record of the project's binding constraints; a conflict
between it and any other document is a defect to be resolved by amending this
constitution, not ignored.

- **Amendments** MUST be made by editing this file, documenting the change in
  the Sync Impact Report, and bumping the version.
- **Versioning policy** (semantic): MAJOR for backward-incompatible governance
  or principle removals/redefinitions; MINOR for a new principle/section or
  materially expanded guidance; PATCH for clarifications and non-semantic
  refinements.
- **Compliance**: every PR/review verifies the change complies with these
  principles. Any added complexity that appears to violate Principle IV MUST be
  justified in the change (e.g. the plan's Complexity Tracking table) with the
  simpler alternative and why it was rejected.
- **Runtime guidance**: `AGENTS.md` (and `CLAUDE.md`, which includes it) is the
  operational guidance for day-to-day development and MUST be kept consistent
  with this constitution.

**Version**: 1.6.0 | **Ratified**: 2026-07-21 | **Last Amended**: 2026-10-05
