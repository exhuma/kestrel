# Implementation Plan: Jira Ingestion & Autonomous Design/Code/Verify Loop

**Branch**: `003-jira-ingestion` | **Date**: 2026-07-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `.specify/specs/003-jira-ingestion/spec.md`

## Summary

1. **Ingest RFCs from Jira by polling** (US1). A background poll loop queries a
   configured Jira project with a configured JQL filter, and for each qualifying RFC
   resolves the target code repository from a **configurable Jira field**, then starts a
   run through a **source-neutral** ingestion entry point. No off-loopback endpoint is
   added — polling is the only transport — so, unlike feature 002, this feature adds **no
   new deviation** from the constitution's loopback-bound access model.

2. **Extract the Task Source / Code Host seam** (US4). The `GitHubClient` — which today
   mixes ticket operations and repository operations — is split behind two ports: a
   `TaskSource` (read a ticket, comment on it, attach to it, deep-link to it, publish the
   approved PRD to it) and a `CodeHost` (default branch, provision worktree, open a
   merge/pull request). GitHub implements both; Jira implements `TaskSource` and delegates
   the `CodeHost` role to the operator-configured code host. Consistent with kestrel's
   **sovereignty** posture (self-hostable, no mandatory external cloud), the `CodeHost` ships
   **two** first-class implementations — GitHub and a **self-hosted git host** (GitLab as the
   reference; Gitea/Forgejo the same port) — so a Jira-resolved repo can live on an on-prem
   GitLab. This is the abstraction feature 002 deliberately deferred ("seam now, extract with
   the second source"); two concrete task sources *and* two concrete code hosts now exist, so
   the extraction is justified (Constitution IV).

3. **Reshape the workflow into one unified, source-agnostic pipeline** (US2, US3). The
   existing `refine → plan → implement` becomes `refine → (PRD approval) → design → code →
   verify → change-request`, identical for **every** source. The single human gate is PRD
   approval; clarification during refine also pauses for human input. Everything after PRD
   approval — design, code, verify — runs **gateless**. A new **verifier** step judges the
   implementation against the PRD/design and either accepts (→ open the change request) or
   returns work to the coder with feedback, bounded by a configurable max-iteration count;
   on exhaustion the run **escalates** to the ticket instead of looping forever. The design
   **assumes** the verifier grounds its verdict in the **observed behaviour of the running,
   modified project** — it runs the project in the isolated worktree and exercises its real
   boundary (real HTTP requests for an HTTP API such as FastAPI; browser automation via
   Playwright for a web GUI such as a Vite app), the two initial supported boundaries. The
   exact behavioural harness is **not required in full by this feature** (delivered
   incrementally); v1 ships the generic `Observation`/`Evidence` interface, the
   verifier-as-adjudicator role + the failing-observation invariant, and a minimal interim
   gatherer (configured checks), so later delivery of the HTTP/Playwright harness does not
   reshape the workflow.

4. **Route all human/agent contact through the ticket, thinly** (US2, cross-cutting).
   Clarification, PRD-approval, escalation, and change-request notifications are posted as
   comments through the existing `Notifier` port (now source-dispatching), carrying only a
   status and a deep-link/CR-link — never PRD, design, plan, or questionnaire content. The
   PRD is delivered as a ticket **attachment**, not inlined.

**Binding constraints** (from `.specify/memory/constitution.md` v1.2.0): all logic stays in
backend services (routers → services → stores); the schema change ships as Alembic
migration `0007` (no `create_all`/raw DDL); behaviour ships with pytest/vitest that mock the
Jira API and the agent backends (no real `claude`, no real Jira, no production DB); Jira
credentials come from `pydantic-settings` and are never logged or committed; stores keep
their own `Session` lifecycle and naive-UTC timestamps; the run `source` stays backend-only
and MUST NOT drive which phases/gates a run traverses. **No new dependency** is introduced —
the Jira client reuses `httpx`, already used by `GitHubClient`.

## Technical Context

**Language/Version**: Python 3.12 (backend, `uv`), TypeScript 5 / Vue 3 (frontend, `npm`).

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x, Alembic, pydantic-settings, `httpx`
(existing — reused for the Jira client and the self-hosted-git `CodeHost`), Vue 3 + Vuetify 4.
No new runtime dependency. The v1 verify evidence gatherer shells out (existing subprocess
helper). The assumed behavioural harness would later add Playwright for the GUI boundary (HTTP
exercise reuses `httpx`); **Playwright is a deferred/assumed dependency, not added by this
feature**.

**Storage**: SQLite via SQLAlchemy 2.x, schema owned by Alembic. One new migration `0007`
(add `workflow_run.task_ref`; make `issue_number` nullable; generalize the dismissal table
to a source-neutral `task_ref` key). New run `source` value `"jira-issue"` needs no schema
change.

**Testing**: pytest with `httpx` transport mocking for the Jira/GitHub clients and stubbed
agent backends; vitest for the frontend status/step-label additions. No real `claude`
subprocess, no real Jira, no production database (Constitution III).

**Target Platform**: single-user Linux service, API loopback-bound and unauthenticated;
Jira reached outbound over HTTPS; no inbound endpoint added.

**Project Type**: web application (FastAPI backend in `backend/`, Vue SPA in `frontend/`).

**Performance Goals**: not latency-sensitive; poll cadence configurable (default 300 s). A
poll cycle must not block request handling (runs on the lifespan asyncio loop, like the
existing GitHub reconciler).

**Constraints**: no off-loopback endpoint (poll-only); one human gate (PRD approval) plus
refine clarification; design/code/verify gateless; verify loop bounded by
`max_verify_iterations`; verifier grounded in the running project's observed behaviour (assumed
model: HTTP requests for APIs, Playwright for GUIs — harness delivered incrementally; v1 ships
the evidence interface + a minimal `check` gatherer); self-hostable code host (no mandatory
external cloud); thin ticket notifications (no internal content); secrets never logged.

**Scale/Scope**: single maintainer; a handful of concurrent runs; RFC volume small (a team's
change requests). Poll query returns a bounded page of qualifying RFCs per cycle.

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.2.0.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Contract Fidelity | ✅ **No new deviation** | Poll-only ingestion adds **no** off-loopback endpoint, so — unlike feature 002 — this feature needs **no constitution amendment**. The deep-link reuses the already-recorded public-UI posture (v1.2.0). Type contract: `source` gains `"jira-issue"` but stays backend-only (not in the API schema / `frontend/src/types/`) and MUST NOT affect phases/gates (FR-026). The reshaped workflow changes the `status`/step-name **enum values** the frontend renders (new: `designing`/`coding`/`verifying`/`escalated`, steps `design`/`code`/`verify`); both sides are updated together so the contract stays in sync. |
| II. Layered, Backend-Owned Architecture | ✅ | All ingestion, resolution, refinement, the design/code/verify loop, verification, and notification live in backend services (`services/jira.py`, `services/jira_poll.py`, `services/ingestion.py`, `services/workflows.py`) behind routers. The frontend only renders state and follows deep-links. Schema change is Alembic `0007` — no `create_all`/raw DDL. |
| III. Test-First Discipline | ✅ | Each unit ships with tests: Jira client (search/get/comment/attach/field-read, httpx mocked), repo resolution (resolved / empty / unreachable), source-neutral ingestion + dismissal, one-run-per-`task_ref`, verify loop (accept / reject-then-accept / exhaust→escalate), notifier source-dispatch + best-effort failure, PRD attachment, migration up/down. No real `claude`/Jira; frontend statuses/steps in vitest. |
| IV. Deliberate Simplicity & Single-User Scope | ⚠️ **Justified complexity** | Seven additions carry justified complexity — the Task Source/Code Host extraction, a self-hosted-git `CodeHost` (GitLab reference), the Jira poll loop, the source-neutral `task_ref` identity, the verify loop + iteration bound + escalation, the evidence check runner, and the source-dispatching notifier — each recorded in Complexity Tracking with the simpler alternative and why it is insufficient. Each is need-driven by the sovereignty positioning and the two-concrete-implementations test, not speculative. No multi-user auth; Jira/code-host tokens are outbound credentials, not access gates. YAGNI boundaries (below) are explicit. |
| V. Kit-Aligned Consistency & Observability | ✅ | Structured logging records each RFC observation outcome (started / skipped-duplicate / skipped-filtered / unresolved-repo / dismissed / failed — FR-035) with credentials redacted (FR-004). No hard-coded colours (new status chips use existing theme tokens). `.env.example` documents the `KESTREL_JIRA_*` settings; `.env` stays untracked. Kits resolved per task. |

**Gate result**: PASS. No prerequisite constitution amendment is required (contrast with
feature 002): poll-only ingestion introduces no new off-loopback surface. Complexity is
recorded and justified below.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/003-jira-ingestion/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── task-source-port.md
│   ├── code-host-port.md
│   ├── jira-client.md
│   ├── ingestion-and-poll.md
│   ├── verify-evidence.md
│   └── workflow-states.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks output (not created here)
```

### Source code (repository root) — files touched / added

```text
backend/app/
├── ports.py                          # NEW — TaskSource, CodeHost protocols + Task, Observation, Evidence
├── services/
│   ├── jira.py                       # NEW — JiraClient (httpx) + JiraTaskSource impl
│   ├── jira_poll.py                  # NEW — Jira poll service (mirrors reconcile.py)
│   ├── gitlab.py                     # NEW — GitLabCodeHost (self-hosted git host; merge requests)
│   ├── checks.py                     # NEW — v1 interim evidence gatherer (configured checks → Evidence); behavioural HTTP/Playwright harness deferred
│   ├── github.py                     # SPLIT — GitHubTaskSource + GitHubCodeHost over GitHubClient
│   ├── ingestion.py                  # GENERALIZE — source-neutral maybe_start_run(task_ref, …)
│   ├── reconcile.py                  # ADAPT — call the generalized ingestion entry point
│   └── workflows.py                  # RESHAPE — design/code/verify, verify loop + evidence, escalation, ports
├── notifications.py                  # CHANGE — TaskSourceNotifier (dispatch by source); render via task_ref
├── policy.py                         # CHANGE — DEFAULT_MODELS/STEP_REQUIREMENTS: design/code/verify
├── config.py                         # ADD — KESTREL_JIRA_*, KESTREL_CODE_HOST_*, KESTREL_VERIFY_CHECKS, max_verify_iterations
├── models_workflow.py               # ADD — WorkflowRun.task_ref; issue_number Optional
├── persistence/
│   ├── tables.py                     # ADD — task_ref column; issue_number nullable; dismissal task_ref
│   └── dismissal_store.py            # GENERALIZE — key by task_ref
├── main.py                           # ADD — start Jira poll task in lifespan when configured
└── alembic/versions/0007_jira_ingestion.py   # NEW migration

frontend/src/
├── (status/step label + chip maps)   # ADD designing/coding/verifying/escalated; design/code/verify
└── types/                            # UNCHANGED shape — no `source`; enum-value additions only

backend/tests/… , frontend/tests/…    # NEW tests per Constitution III
.env.example                          # ADD documented KESTREL_JIRA_* keys
docs/architecture.md, docs/*          # UPDATE — Jira source, unified workflow, verify loop
```

**Structure Decision**: The existing `backend/` + `frontend/` split and the
routers → services → stores layering are unchanged. New Jira concerns are additive services;
the workflow reshape edits `services/workflows.py` and `policy.py` in place; the
Task Source/Code Host split turns `services/github.py`'s single client into two port
implementations without changing the network calls it already makes.

**Extensibility / future sources (seam, not framework)**: The ports are the extraction point
feature 002 named. A third **task source** (GitLab issues, Planka) implements `TaskSource`; a
non-GitHub **code host** (GitLab merge requests) implements `CodeHost`. This feature ships
exactly two `TaskSource` implementations (GitHub, Jira) and **one** `CodeHost` (GitHub); it
does not build a registry/plugin framework — sources are wired in the `WorkflowService`
factory and the two poll/webhook callers, matching how backends are wired today.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| **Task Source / Code Host port extraction** (`ports.py`; split `github.py`) | Jira separates the ticket (Jira) from the code (a git repo); a run needs both, and the workflow/notifier must not hard-code GitHub. Two concrete sources now exist (Constitution IV's trigger for extraction) | Keeping `GitHubClient` and branching on `source` inside the workflow scatters `if source == "jira"` through `_drive`/`_deliver`/notifier — the exact GitHub coupling 002 warned against, and it blocks a third source. A full plugin registry is the opposite over-reach (rejected as YAGNI) |
| **Source-neutral `task_ref` identity** (new `workflow_run.task_ref`; generalized dismissal) | A Jira RFC has no `(repo, issue_number)`; dedup, one-run-per-ticket, dismissal, and notification rendering all need one identity that works for both sources | Storing a fake `issue_number` for Jira leaks GitHub shape everywhere and collides in the dismissal PK. A second parallel Jira-only dismissal table duplicates the guard logic and desyncs the two paths |
| **Jira poll loop** (`services/jira_poll.py`, lifespan task) | Jira may offer no webhook; a qualifying RFC must still produce exactly one run. No existing scheduler covers Jira | A manual "scan Jira" button reintroduces the hand-triggering the feature removes. An external cron adds an operational dependency for a single-user tool. Reuses the proven `ReconcileService` shape, so cost is low |
| **Verify loop + iteration bound + `escalated` state** | The autonomy goal requires a machine gate (the verifier) replacing the removed human approval, and it must terminate — an unbounded design→code→verify cycle is a hang | No verifier = shipping unverified autonomous code (defeats the goal). No bound = possible infinite loop. "Open the MR anyway on exhaustion" was offered and **rejected by the requester** in favour of escalation |
| **Source-dispatching `TaskSourceNotifier`** (replaces `GitHubIssueNotifier`) | A run's gate comment must go to *its* ticket (Jira or GitHub) via that source's `post_comment`; the notifier can no longer assume GitHub | N separate notifiers each no-op'ing on the wrong `source` fan out redundantly and re-check the discriminator per notifier. One dispatcher keyed by `run.source` is smaller and centralizes the best-effort/thin-content rules (FR-028/FR-029) |
| **Self-hosted-git `CodeHost`** (`services/gitlab.py`; GitLab reference, Gitea/Forgejo same port) | The sovereignty target customer runs code on a self-hosted git host, not GitHub.com; a Jira-resolved repo must be able to live on an on-prem GitLab and open a merge request there. Two concrete `CodeHost`s (GitHub + self-hosted) are what justify the port at all | GitHub.com-only would make the feature unusable for the actual target (independence/infosec-minded orgs), and reduce `CodeHost` to a single-impl abstraction (a Constitution IV smell). Reuses `httpx`; no new dependency |
| **Verify evidence interface + interim gatherer** (`ports.py` `Observation`/`Evidence`; `services/checks.py`) | The verifier's verdict must be grounded in the running project's **observed behaviour** (assumed model: HTTP requests for APIs, Playwright for GUIs), not model opinion — sharper under sovereignty, where a weaker on-prem model's unaided judgment is trusted less. v1 carries the generic evidence interface + a minimal `check` gatherer; the behavioural harness is deferred | An LLM-judgment-only verifier ships plausible-but-wrong work — the exact risk the requester wants closed. Building the full HTTP/Playwright harness now is not required by this feature (requester: exact details deferred). The generic `Observation{kind}` interface is the cheap forward-compat move so the harness drops in later with no reshape |

**Not added** (YAGNI):
- **No Jira webhook endpoint** — poll-only (confirmed). The ingestion entry point is
  source-neutral so a future webhook is one added caller (FR-034); it is not built now, and
  building it would add the second off-loopback exception (a MINOR amendment) prematurely.
- **Code host: GitHub + one self-hosted git host (GitLab reference) only** — Gitea/Forgejo and
  any further host are the same port with different endpoints, added as needed. `KESTREL_CODE_HOST`
  selects the type; the reference self-hosted impl is GitLab (best REST MR API, common in
  regulated/sovereign orgs). If the target deployment runs Gitea/Forgejo instead, swap the
  reference impl — the port and config are unchanged.
- **Verify grounding is minimal in v1; behavioural harness deferred** — the design assumes the
  verifier runs the modified project and exercises its boundary (HTTP requests for APIs,
  Playwright for GUIs), but the **exact behavioural harness (app launch, request/interaction
  scripting, browser automation, boundary detection) is not built now** (requester: exact details
  deferred, delivered incrementally). v1 ships the generic `Observation`/`Evidence` interface + a
  minimal `check` gatherer. **Playwright is an assumed future dependency, not added now.** Richer
  executable acceptance criteria emitted by refinement/design are likewise deferred.
- **No Jira-comment-reply / status-transition ingestion** — clarification answers and PRD
  approval happen in the kestrel questionnaire/approval UI via the deep-link (confirmed);
  parsing free-text Jira replies is deferred.
- **No persisted verify-iteration counter for resume** — the loop lives in the transient
  driver coroutine; a restart mid-loop fails loudly like every other transient state
  (`recover()`), so the counter is in-memory and bounded. No new "resume the loop" machinery.
- **No multi-repository RFCs** — one RFC resolves to one target repository.
