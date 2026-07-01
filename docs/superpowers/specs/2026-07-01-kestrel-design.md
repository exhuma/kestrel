# Kestrel — PRD / SRD & Delivery Roadmap

## Context

The repo currently holds a **verified feasibility spike**
(`2026-06-30-agent-dispatcher-spike-design.md`) that de-risks one thing:
kestrel can spawn a host `claude -p` session as an asyncio subprocess, stream
its `stream-json` JSONL events to a Vue/Vuetify browser via SSE, and *resume
that exact session* with new input — all on a flat-rate **Max subscription**
(no API key), running non-interactively with `--permission-mode acceptEdits`.
The spike is intentionally single-user, in-memory, and has no GitHub, no
persistence, no workflow, and only a raw-JSON event view.

This document turns that spike into **kestrel**: a single-user assistant that
**proactively works on tasks from external sources** — MVP source is **GitHub
issues** — by refining each task through structured, human-in-the-loop gates
and then implementing it autonomously and opening a PR.

The project is **deliberately single-user**. Multi-user is a non-goal and is
removed from the roadmap. The only access control considered is an optional,
non-urgent **access gate** (a single shared secret) to stop others tampering.

This design supersedes the spike doc's single-service framing.

### Decisions locked with the user
- **Interview & approval surface:** the **kestrel web UI** — questions rendered
  as rich structured forms from a JSON questionnaire schema; approvals are UI
  buttons.
- **Model-selection driver:** conserve **Max rate-limit quota** (flat fee, no
  per-token cost, but Opus drains the 5h/weekly quota fast). Selection is done
  per workflow step via the `claude --model` flag.
- **Implementation-blocker handling:** **pause & re-interview** — suspend the
  run, raise a structured question, resume once answered.
- **Trigger:** **GitHub webhooks** (HMAC-verified), with polling reconciliation
  as a safety net for missed deliveries.
- **Notifications:** delivered through a **pluggable `Notifier` interface**;
  in-app ships first, other channels drop in later.

---

## Part 1 — Product Requirements (PRD)

### 1.1 Vision
A personal, always-on assistant that picks up incoming work items, sharpens
them with the human just enough to remove ambiguity, and then drives them to a
reviewable PR with minimal babysitting. Kestrel optimises for **ergonomics**
(low-friction interaction) and **frugality** (cheap models and deterministic
code wherever an LLM is not truly needed).

### 1.2 Users & usage
- **Single user** (the owner). No accounts, roles, or tenancy.
- Runs self-hosted on the owner's machine/box, using the owner's logged-in
  `claude` Max session.

### 1.3 Sources (extensibility)
- **MVP:** GitHub issues.
- **Later (out of scope now, but the source layer must be pluggable):** Planka
  kanban cards, Zammad tickets. A `TaskSource` interface isolates source
  specifics (fetch item, post comment, apply edits, open PR/equivalent) so new
  sources drop in without touching the orchestrator.

### 1.4 Core workflow (the product)
Each issue flows through a persisted **state machine**. Every arrow is either a
deterministic transition or a single, model-selected Claude step.

1. **Issue created/updated** → webhook received (deterministic).
2. **Gap analysis** — Claude inspects the issue for ambiguities/gaps.
3. **Clarification interview** — if gaps exist, kestrel presents a **structured
   questionnaire** (JSON schema → rich UI form). User answers.
4. **Propose issue description** — Claude drafts a refined description.
   - **Reject (no prompt)** → stop.
   - **Reject + refinement prompt** → Claude reformulates; back to propose.
   - **Approve** → kestrel writes the new text back to the GitHub issue.
5. **Plan** — Claude drafts an implementation plan.
   - **Reject (no prompt)** → stop.
   - **Reject + refinement prompt** → Claude reformulates; back to propose.
   - **Approve** → implementation starts immediately, hands-off.
6. **Autonomous implementation** — Claude works in an isolated worktree.
   - On a **blocker** (failing tests / real ambiguity / stuck): **pause**, raise
     a structured question via the interview surface, **resume** on answer.
7. **PR** — kestrel opens a PR (draft if it exited via an unresolved blocker)
   and **notifies** the user.

### 1.5 Ergonomics requirements
- Interviews are **structured questionnaires**, never free-form walls of text:
  each question carries a type (single/multi-select, boolean, free-text), the
  **"why"** behind it, options, and required-ness — enabling a rich form UI.
- The event stream is shown in a **human-friendly view** (assistant messages as
  chat, tool calls as collapsible cards, thinking collapsed, result summarised)
  with the **raw JSON always accessible** behind a toggle/drawer.
- A **per-issue dashboard/timeline** shows the current state and history at a
  glance; pending user actions (answer questionnaire / approve) are surfaced.
- User gets **notified** when their input is needed and when a PR is ready.
  Notification delivery is a **pluggable interface** (see SRD §2.2): channels
  (in-app, later email/push/etc.) are drop-in back-ends behind one `Notifier`
  contract, so the workflow never hardcodes a channel.

### 1.6 Frugality requirements
- **Deterministic-first:** anything that isn't genuine reasoning is plain code
  (webhook verify, GitHub calls, git/worktree ops, PR creation, schema
  validation, state transitions, notifications, model-policy lookup).
- **Per-step model policy:** each Claude step maps to the cheapest adequate
  model; expensive models only where they earn it (see SRD §2.7).
- Globally-installed MCP servers are available to Claude sessions automatically
  once configured — no per-session wiring needed.

### 1.7 Success criteria
- An issue can traverse the full lifecycle end-to-end and produce a PR with no
  more than the two designed approval gates plus any clarification answers.
- State survives a process restart at every gate (durable).
- Default runs use no Opus except where the model policy explicitly allows it.
- The raw-JSON firehose is replaced by a readable view without losing raw data.

### 1.8 Non-goals
- Multi-user / tenancy / accounts.
- Per-token API-key billing model (kestrel targets the Max subscription).
- Sources other than GitHub (interface only; no implementations yet).
- Heavyweight infra (managed Postgres cluster, queues) — single-user scale.

---

## Part 2 — Software Requirements (SRD)

### 2.1 Architecture (evolution of the spike)
```
GitHub ──webhook──▶ FastAPI (kestrel)
                      ├─ Ingestion (verify HMAC, dedup)            [deterministic]
                      ├─ Orchestrator: persisted state machine
                      │     └─ StepRunner ─▶ SessionRunner ─▶ claude -p --model …
                      ├─ TaskSource (GitHub impl): fetch/comment/edit/PR   [det.]
                      ├─ Repo workspace mgr: clone + git worktree per issue [det.]
                      ├─ Questionnaire: JSON schema + validation           [det.]
                      ├─ Persistence (SQLite)                              [det.]
                      └─ SSE + REST  ─▶  Vue/Vuetify UI (forms, timeline, events)
```
Keep the spike's proven core: `SessionRunner` (subprocess + `stream-json`
parsing), the pub/sub registry (now backed by durable storage), and SSE fan-out.

### 2.2 Backend components
- **`orchestrator/`** — the workflow state machine + `StepRunner`
  (wraps `SessionRunner`, applies the model policy, records step I/O).
- **`sources/`** — `TaskSource` protocol + `GitHubSource` implementation
  (via the GitHub REST API; issue fetch, comment, description edit, branch +
  PR create).
- **`ingestion/`** — webhook route, HMAC signature verification, event dedup,
  plus a periodic **poll-reconcile** job for missed webhooks.
- **`workspace/`** — target-repo checkout + `git worktree` lifecycle per issue,
  branch naming, commit/push, cleanup.
- **`questionnaire/`** — JSON schema, validation, and the Claude output contract
  for gap analysis and question generation.
- **`persistence/`** — SQLite via SQLAlchemy; the in-memory registry becomes a
  write-through cache over durable tables.
- **`policy/`** — model-selection policy (step → model), config-overridable.
- **`notifications/`** — a **pluggable `Notifier` interface** (protocol:
  `notify(event, work_item, payload)`), with pluggable back-ends registered by
  config. MVP ships an **in-app** notifier (persisted + surfaced over SSE);
  email/push/webhook/etc. drop in later without touching the orchestrator. The
  orchestrator only depends on the `Notifier` protocol, never a concrete
  channel.
- Existing `routers/`, `services/runner.py`, `storage/registry.py`, `config.py`
  (`env_prefix` renamed `DISPATCHER_` → `KESTREL_`) are refactored, not
  rewritten.

### 2.3 State machine (persisted per work item)
`intake → analyzing → awaiting_clarification → proposing_description →
awaiting_description_approval → updating_issue → planning →
awaiting_plan_approval → implementing → (paused_for_clarification ⇄
implementing) → creating_pr → done`
with terminal `rejected` and `failed`. Every state is persisted; transitions
are pure functions over `(state, event)` and are unit-testable without GitHub or
Claude.

### 2.4 Data model (SQLite)
- `work_item` — source, external id (repo+issue#), current state, timestamps.
- `session` — the Claude session(s) per item (session_id, cwd/worktree, model,
  step name, status). Replaces the spike's in-memory `SessionRecord`.
- `event` — persisted parsed events (type, session_id, raw JSON) for replay.
- `questionnaire` / `answer` — issued questions and the user's responses.
- `proposal` — description/plan drafts, their approval status and refinement
  prompts.
Schema evolution via lightweight migrations (Alembic or a simple versioned
runner); **no `create_all` in app code**.

### 2.5 Questionnaire schema (illustrative)
```json
{
  "questionnaire_id": "uuid",
  "title": "Clarifications for issue #42",
  "questions": [
    {"id": "q1", "prompt": "Which auth flow?",
     "why": "The issue says 'login' but not the mechanism.",
     "type": "single_select", "required": true,
     "options": [{"value": "oidc", "label": "OIDC"},
                 {"value": "local", "label": "Local password"}]},
    {"id": "q2", "prompt": "Anything else we should know?",
     "why": "Catch-all for missed context.",
     "type": "free_text", "required": false}
  ]
}
```
Claude is instructed to emit exactly this shape (validated deterministically;
reject+retry on schema violation). The same schema drives both mid-refinement
questionnaires and mid-implementation clarification pauses.

### 2.6 Interfaces (REST/SSE, additive to the spike)
- `POST /api/webhooks/github` — verified ingress.
- `GET /api/work-items`, `GET /api/work-items/{id}` — dashboard/timeline.
- `GET /api/work-items/{id}/questionnaire` + `POST …/answers`.
- `POST …/description/{approve|reject}` (reject body may carry a refinement
  prompt); same for `…/plan/{approve|reject}`.
- `GET /api/sessions/{id}/events` (SSE) — retained from spike, now durable.

### 2.7 Model-selection policy (Max-quota frugal)
Default step → model map (config-overridable):
- **Gap analysis / questionnaire generation:** Haiku → escalate to Sonnet if
  the issue is large/complex.
- **Description reformulation:** Sonnet.
- **Plan generation:** Sonnet (Opus only on explicit opt-in — planning is
  high-value but Sonnet is usually adequate).
- **Autonomous implementation:** Sonnet by default; Opus opt-in per item.
- **Mid-run clarification question generation:** Haiku/Sonnet.
- **Deterministic (no model):** everything in §1.6.
Rationale: on Max, cost = quota burn; keep Opus off the default path.

### 2.8 Security & deployment
- Webhook endpoint verifies GitHub HMAC (`X-Hub-Signature-256`) with a shared
  secret; rejects unsigned/replayed deliveries.
- Public reachability for webhooks via a tunnel/reverse proxy (cloudflared /
  ngrok / nginx) — documented, not built.
- Optional **access gate** (later, low priority): single shared secret / basic
  auth in front of the UI/API. The frontend `TokenProvider` seam already exists.
- Secrets via env (`KESTREL_*`) / `.env` (git-ignored), documented `.env.example`.

### 2.9 Conventions (inherited, non-negotiable)
80-char lines; backend `uv` only, `create_app()` factory, pydantic-settings;
frontend `npm` only, Vue `<script setup lang="ts">`, vanilla `fetch` via
`src/api`, module-singleton composables, no Pinia; pytest + vitest with
"Ensure …" docstrings; Sphinx docstrings + full type hints on the backend.

---

## Part 3 — Delivery Roadmap (manageable chunks)

Each milestone is an independent spec→plan→implement cycle. Ordered by
dependency. Cross-cutting concerns (model policy, persistence) land early so
later work builds on them.

- **M-A · Foundation & rename.** Rename project/config to **kestrel**
  (`KESTREL_` env prefix, docs, package metadata). Add **SQLite persistence**
  (SQLAlchemy + migrations) behind the existing registry. Add the small
  **model-policy** module. Spike mechanic still works end-to-end. *No new
  behaviour — pure groundwork.*
- **M-B · Orchestrator state machine.** Durable `work_item` + the §2.3 state
  machine + `StepRunner` (wraps `SessionRunner`, applies model policy). Drive
  the full lifecycle with **manual/stubbed** inputs (no GitHub yet). Fully
  unit-tested transitions.
- **M-C · GitHub ingestion & repo ops.** Webhook route + HMAC verify + dedup +
  poll reconciliation; `GitHubSource` (fetch/comment/edit/PR); `workspace`
  worktree lifecycle. Deterministic, testable against the GitHub API with a
  recorded fixture.
- **M-D · Interview subsystem.** Questionnaire JSON schema + validation + Claude
  output contract for gap analysis; **web-UI form renderer**; answer capture;
  wire into `awaiting_clarification`.
- **M-E · Proposal & approval gates.** Description reformulation + plan
  generation steps; approve/reject/**refine** loop in the UI for both gates;
  write approved description back to the issue.
- **M-F · Autonomous implementation + pause/re-interview + PR.** Run
  implementation in a worktree; blocker detection → **pause → clarify →
  resume**; commit/push; open (draft-on-blocker) PR; notify.
- **M-G · UI overhaul & ergonomics.** Human-friendly typed event rendering with
  raw-JSON toggle; per-issue dashboard/timeline; the **`Notifier` interface** +
  in-app notification back-end + notification center. The pluggable seam is
  built here even though only the in-app channel ships.
- **M-H · Deferred / optional.** Access gate; additional `Notifier` back-ends
  (email/push — e.g. via the claude.ai Gmail connector once authorized);
  additional sources (Planka, Zammad) via `TaskSource`.

---

## Verification (per milestone, end-to-end)
- **Automated:** `uv run pytest` (backend) and `npm test` (frontend) green;
  state-machine transitions covered by table-driven unit tests; questionnaire
  schema validation covered incl. malformed-Claude-output retry.
- **Manual E2E (M-C onward):** create a real GitHub issue in a sandbox repo →
  observe webhook intake → answer a questionnaire in the UI → approve
  description (verify GitHub issue text updated) → approve plan → watch
  implementation stream in the human-friendly view → confirm a PR is opened and
  a notification fires. Restart the backend mid-flow at a gate to confirm state
  is restored from SQLite.
- **Frugality check:** inspect recorded per-step `model` values; confirm no Opus
  on the default path.
