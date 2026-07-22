# Phase 0 Research: GitHub Ingestion & Repo Ops

Decisions resolving the plan's unknowns. Each: **Decision / Rationale /
Alternatives**. Grounded in the current code (file:line where it anchors).

## R-01 — Webhook signature verification

**Decision**: Verify `X-Hub-Signature-256` as
`sha256=` + `hmac.new(webhook_secret, raw_body, hashlib.sha256).hexdigest()`,
compared with `hmac.compare_digest` (constant-time — FR-003). Read the **raw**
request body (`await request.body()`) before any JSON parsing, because the HMAC is
over the exact bytes GitHub sent. Implement as a FastAPI dependency on the webhook
router so the handler only runs on authentic deliveries.

**Rationale**: Matches GitHub's documented scheme; stdlib only (no new dep). There
is no signature/auth code in the app today (routers use only `Depends` on
singletons), so this is introduced from scratch, isolated to the one endpoint.

**Alternatives**: SHA-1 `X-Hub-Signature` (deprecated by GitHub — rejected); a
global middleware (rejected — would wrongly touch loopback API routes; the rest of
the API stays unauthenticated per the constitution).

## R-02 — Delivery dedup & retention

**Decision**: A `webhook_delivery` table keyed by GitHub's `X-GitHub-Delivery`
UUID, with `event`, `outcome`, `created_at`. A `WebhookDeliveryStore.seen(id)`
does an atomic insert-if-absent and returns whether it was already present (FR-004).
On each insert, prune rows older than a fixed retention window (7 days, well past
GitHub's ~24 h redelivery window) to bound growth (FR-008/SC-008). Survives restart
because it is in SQLite (FR-022).

**Rationale**: Mirrors the existing write-through store pattern
(`persistence/notification_store.py:38-49`, `with self._factory.begin()`). Insert
races are resolved by the PK uniqueness on the delivery id.

**Alternatives**: In-memory set (loses state on restart → double-start on
retry-after-restart — rejected); unbounded table (violates SC-008 — rejected);
a configurable retention (deferred — a constant is simpler and single-user scope
doesn't need tuning).

## R-03 — Ingestion path shared by webhook + reconciliation

**Decision**: A single `ingestion.py` service exposes
`maybe_start_run(repo, issue_number, *, source="github-issue")` that: (1) checks
the repo is in `watched_repos`; (2) skips if the (repo,issue) is **dismissed**
(FR-008a — see R-13); (3) enforces one-run-per-(repo,issue) by scanning
`workflows.list()` for an existing run with that repo+issue (FR-008); (4) calls
`WorkflowService.create(..., source=source)`. Both the webhook handler and the
reconciliation loop call this, guaranteeing webhook/poll idempotency (FR-013) by
construction. Label-match and event-type gating happen in the webhook handler
before this call; reconciliation only ever lists already-labelled issues.

**Rationale**: DRY — one dedup rule, one start path. `WorkflowService.create()`
(`services/workflows.py:379-398`) is already the single run-creation site; the
task-source concern (FR-019) attaches here.

**Alternatives**: Duplicating the guard in each caller (rejected — two places to
get the "at most one run" invariant wrong). A distributed lock (unneeded — single
process; the guard runs under asyncio's single thread, and creation is cheap).

## R-04 — One-run-per-(repo,issue) guard & race handling

**Decision**: Before creating, scan in-memory `workflows.list()` for any run with
matching `repo` and `issue_number` regardless of status (an already-failed/done run
still blocks a duplicate; re-running is a manual action per the spec's Assumptions).
Because all creation is funnelled through `ingestion.maybe_start_run` and asyncio
runs it without preemption between the scan and `create()`, the webhook-vs-reconcile
race (Edge Case) cannot double-create.

**Rationale**: The registry is an in-memory `dict` (`workflow_registry.py:13-100`);
the scan is O(runs) and single-user scale makes it trivial. No new index needed.

**Alternatives**: A unique DB constraint on `(repo, issue_number)` — attractive but
`workflow_run` has no such column pair indexed and a manual re-run is a legitimate
future second row; enforcing at the service layer keeps the "manual re-run" door
open without a schema fight. Revisit if a DB-level guarantee is later wanted.

## R-05 — Task source (FR-019)

**Decision**: Add `WorkflowRun.source: str` defaulting to `"manual"`; ingestion
passes `"github-issue"`. Persist as a `source` column on `workflow_run` (default
`"manual"` for existing rows). It is **internal-only** — NOT added to the API
schema (`schemas.py`) or the frontend type (clarification Q3), so ingested and
manual runs stay visually indistinguishable (FR-009). The repo+issue it carries
already live on the run, so no separate source entity is needed — the string
discriminator is the minimum that makes origin identifiable and lets future sources
be added without reworking run execution.

**Rationale**: YAGNI — the spec's "Task Source" entity only needs to *attribute* a
run internally and leave room for future sources. Surfacing it to the UI would add
API + type-contract work and tension FR-009 for no required benefit (Principle IV).

**Alternatives**: Surface `source` in `WorkflowSummary`/`Detail` + frontend type
(rejected — clarification Q3: no FR needs UI origin display, and it tensions FR-009).
A dedicated `task_source` table / polymorphic model (rejected as premature). No
field at all (rejected — FR-019 requires source be identifiable).

## R-06 — Notifier composition & async posting

**Decision**: Keep the `Notifier` protocol **synchronous**
(`notifications.py:96-101`). Add `GitHubIssueNotifier` whose `notify(run)`, for an
`awaiting_*` status, renders the existing template (`render_message`) + a deep-link
and schedules the GitHub POST as fire-and-forget (`asyncio.create_task`) wrapped in
try/except that logs failures (FR-026). Add `CompositeNotifier([...])` fanning out
to `InAppNotifier` first (always records — the fallback) then `GitHubIssueNotifier`.
Wire the composite in the service factory (`services/workflows.py:1536-1538`).

**Rationale**: `_save()` (`workflows.py:336-356`) is synchronous and on the run's
critical path; a blocking network call there would violate FR-005's fast-ACK and
stall the driver. Fire-and-forget keeps `_save()` cheap and makes a GitHub outage a
logged no-op, with the in-app row already written.

**Alternatives**: Make `Notifier` async and `await` the post in `_save` (rejected —
couples run progress to GitHub availability, changes every call site, risks
blocking the webhook ACK). A background outbox queue (rejected — YAGNI; in-app is
the agreed fallback, no retry required per clarification Q2).

## R-07 — Restart idempotency of gate comments (satisfies FR-030 without new state)

**Decision**: Post **no** durable "last gate notified" marker. Restart idempotency
is already guaranteed by the recovery design: `recover()`
(`workflows.py:589-605`) re-spawns `_resume()` for `awaiting_*` runs, and every
phase's recovery branch re-parks at the gate **without calling `_save()`** (refine
`:685`,`:729`; plan `:1379`; implement `:1432`,`:1434`). Since the notifier only
fires through `_save()`, a recovered gate never re-notifies — so it never re-posts a
comment. FR-030's *behaviour* (no duplicate comment on restart) holds; the *marker*
its clarification hinted at is unnecessary.

**Rationale**: Reuses an existing, tested invariant instead of adding a table and a
write on every gate. Simpler and less to keep in sync (Principle IV). Documented so
that if a future change makes recovery re-`_save()` at a gate, this guarantee is
revisited (a guard test pins it — see quickstart).

**Alternatives**: A `workflow_id → last_gate` marker table checked before posting
(rejected — redundant given the recovery invariant; more schema and a read/write per
gate). Query the issue's existing comments before posting (rejected — an extra
GitHub round-trip per gate and racy).

## R-08 — Deep-link format & frontend entry

**Decision**: Link is `{public_base_url}/?run={run_id}` — a query param on the SPA
root. On load, `main.ts` reads `new URLSearchParams(location.search).get('run')`
and, if present, calls the singleton `useWorkflows().select(id)`
(`composables/useWorkflows.ts:65`), which opens the run's SSE stream and populates
`current`, driving the whole detail + active-gate form in `WorkflowPanel.vue`
(the active gate is derived from step state at `WorkflowPanel.vue:57-67`, so
selecting the run is sufficient to land on its form — FR-028). No `vue-router`, no
Vite `base` change, no dev-server rewrite.

**Rationale**: The composable is already a module-level singleton whose `select(id)`
works from a bare id and self-populates; a query param is the lowest-friction entry
and survives the static `html=True` SPA mount (`main.py:195-201`). `public_base_url`
is a backend setting (the link is built server-side in the notifier) so the SPA
needs no new build-time env var.

**Alternatives**: `vue-router` + `/runs/:id` path (rejected — pulls in a router and
a `base`/rewrite for the packaged build to serve deep paths; overkill for one link).
Hash `#/<id>` (viable, equivalent; query chosen for simpler parsing and because it
is visible to the backend if ever needed). A frontend `VITE_PUBLIC_BASE_URL`
(rejected — the link is assembled server-side; keep the base in one place).

## R-09 — Worktree isolation model

**Decision**: Per **repo**, maintain one bare mirror under
`{workspace_root}/repos/{owner}__{name}.git` (created with `git clone --bare`/
`--mirror`, fetched before each worktree add). Per **run**, `git worktree add
{workspace_root}/wf-{hex} {base_branch}` then create the run branch in it. Guard
`fetch` + `worktree add`/`worktree remove` for a given repo with an
`asyncio.Lock` from a per-repo lock map (the shared object DB and worktree admin
files are the new shared state — today there is none, git.py:1-82). On terminal
outcome (**done, failed, rejected**, and the existing abandon) run `git worktree
remove --force` and delete the run dir; the bare mirror persists for reuse.

**Rationale**: Gives isolation (separate checkout, index, branch — FR-016) with a
shared object store (no full re-clone per issue), and closes today's leak where
only abandon cleans up (`workflows.py:534-580`; done/failed leave the dir —
`:1501-1517`, `:648-655`). Push/PR still operate on the run's worktree, so external
outcomes are unchanged (FR-018). The per-repo (not global) lock lets unrelated
repos proceed concurrently.

**Alternatives**: Keep per-run full clones (rejected — re-downloads whole repo per
issue, still leaks on done/failed, and does not deliver the milestone's explicit
worktree ask). One global lock (rejected — serialises unrelated repos). No lock
(rejected — concurrent `worktree add` + fetch on a shared object DB can corrupt/
race).

## R-10 — Reconciliation loop

**Decision**: A single `asyncio` task started in `_lifespan` after
`recover()` and before `yield` (`main.py:56-57`), tracked in a module-level task set
(mirroring `_WF_TASKS`, `workflows.py:63`) and cancelled after `yield` on shutdown.
Every `reconcile_interval_seconds` (default 300), for each watched repo it calls
`GitHubClient.list_issues_by_label(repo, trigger_label)` and funnels each issue
through `ingestion.maybe_start_run` (the dedup guard makes re-runs no-ops — FR-013).
Each cycle is wrapped so a GitHub failure (unreachable, rate-limited, unauthorized)
is logged and the loop continues next cycle without starting partial runs (FR-014);
it runs independently of the webhook path (FR-015).

**Rationale**: Reuses the established background-task pattern and the shared
ingestion guard. Interval-driven polling is adequate at single-user scale.

**Alternatives**: External cron/systemd timer (rejected — operational dependency for
a single-user tool). Reusing GitHub's "since" cursors / ETags (deferred optimisation;
label listing at this scale is cheap).

## R-11 — Configuration surface

**Decision**: New `Settings` fields (env `KESTREL_*`, `config.py:64`):
`public_base_url: str = ""`, `webhook_secret: str = ""`,
`trigger_label: str = "kestrel"`, `reconcile_interval_seconds: int = 300`,
`watched_repos: list[str] = []` (comma/JSON list of `owner/name`). `webhook_secret`
is a secret (documented in `.env.example`, never committed — FR-020). A
`model_validator` warns if webhooks/reconciliation are effectively enabled while
`webhook_secret`/`watched_repos` are empty. `github_token` (existing) is reused for
issue reads, reconciliation, and comment posting (auth model unchanged).

**Rationale**: Plain typed settings auto-read from env (`env_prefix="KESTREL_"`);
matches how `github_token`/`git_base` are defined (`config.py:123-125`). No
file-only handling needed (these are not backend config).

**Alternatives**: TOML file-only for watched repos (rejected — env is consistent
with the other GitHub settings and simpler to set in Docker). Env-var indirection
for the secret à la `BackendConfig.secret()` (rejected — a direct secret field is
simplest; Docker/secret-mount handles provisioning).

## R-12 — Comment content & privacy (FR-031, clarification Q3)

**Decision**: Comment bodies come only from the fixed per-status templates
(`notifications.py:42-79`), plus the deep-link line; never the refined description,
plan, or questionnaire content. When `public_base_url` is unset, the same template
posts without the link line (clarification Q3 / decision "post link-less comment").
Secrets/token/signature never appear (FR-006/FR-029).

**Rationale**: The notifier is already deliberately LLM-free and template-driven;
keeping bodies generic guarantees nothing sensitive leaks onto a possibly-public
issue, while the link carries the maintainer to the private UI for the real content.

**Alternatives**: Include a content preview (rejected in clarification — public
exposure risk).

## R-13 — Issue dismissal (tombstone) on abandon (FR-008a, clarification Q1)

**Decision**: An `issue_dismissal` table keyed by `(repo, issue_number)`. A
`DismissalStore` exposes `add(repo, issue)`, `is_dismissed(repo, issue)`, and
`clear(repo, issue)`. Wiring:
- **Abandon** — `WorkflowService.delete` (`workflows.py:534-580`) records a
  dismissal for the run's `(repo, issue)` after tearing the run down.
- **Ingestion** — `maybe_start_run` skips a dismissed `(repo, issue)` (R-03 step 2),
  so neither webhook nor reconciliation re-creates it.
- **Clearing** — two paths, so a missed `unlabeled` webhook still self-heals:
  (a) the webhook handles the `unlabeled` action for the trigger label and calls
  `clear`; (b) each reconciliation cycle computes the set of currently
  trigger-labelled issues per repo and `clear`s any dismissal whose issue is no
  longer in that set (the label was removed). Re-adding the label then starts fresh.

**Rationale**: A durable, restart-surviving record is required (FR-008a) — an
in-memory flag would resurrect an abandoned run after a restart. Keying on
`(repo, issue)` matches the dedup grain. Reconciliation-based clearing makes the
dismissal robust to dropped `unlabeled` deliveries (same best-effort-webhook logic
as the rest of ingestion). Bounded naturally: at most one row per abandoned issue,
removed when the label is dropped.

**Alternatives**: Label is sole source of truth, no tombstone (rejected — Q1: a
still-labelled abandoned issue would loop-restart every cycle). A "handled" marker
that abandon does not clear (rejected — Q1 option C: conflates "started once" with
"user dismissed" and never lets a genuine re-label restart). A status on the run row
instead of a separate table (rejected — abandon deletes the run row, so the record
must outlive it).

## R-14 — Run-start-failure semantics (FR-013a, clarification Q2)

**Decision**: "Run-start failure" means `maybe_start_run` / `WorkflowService.create`
raising **before** a run row is persisted. On such a failure: record the delivery
outcome `run-failed`, leave **no** run record and **no** dismissal, and let the next
reconciliation cycle re-attempt the still-labelled issue (FR-013a). `create()` is
treated as atomic — a failure must not leave a half-created run in the registry/store
(wrap the registry insert so a failure rolls it back). A run that *was* created and
then fails later in the driver is a normal terminal `failed` run: it is **visible**
(the in-app notifier fires on `failed`), not silent, so the maintainer decides
(manual re-run or abandon); reconciliation does not auto-retry an existing run,
which prevents infinite auto-retry of a genuinely broken issue.

**Rationale**: Reuses reconciliation as the retry path (no new retry queue —
Principle IV). Distinguishes "never started" (retry automatically) from "started and
failed" (visible; human decides), which matches the spec's "not left in a state that
silently blocks a later retry" — a `failed` run is not silent.

**Alternatives**: Dedup only after success so webhook redelivery retries (rejected —
Q2: risks double-start on a crash between success and recording). A dedicated retry
queue with backoff (rejected — Q2: YAGNI; reconciliation already covers it).
