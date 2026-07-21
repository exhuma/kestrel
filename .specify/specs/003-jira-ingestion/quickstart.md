# Quickstart: Jira Ingestion & Autonomous Design/Code/Verify Loop

Runnable validation scenarios that prove the feature end-to-end. See
[data-model.md](./data-model.md) and [contracts/](./contracts/) for shapes; this guide is the
run/validation checklist, not implementation.

## Prerequisites

- Apply the migration: `cd backend && uv run alembic upgrade head` (revision
  `0007_jira_ingestion`). Roll back with `alembic downgrade 0006` to verify reversibility.
- Configure Jira in `.env` (documented in `.env.example`; the token is a secret, never
  committed):

  ```bash
  KESTREL_JIRA_BASE_URL=https://your-org.atlassian.net
  KESTREL_JIRA_AUTH=basic                 # basic (Cloud) | bearer (Server/DC)
  KESTREL_JIRA_EMAIL=you@example.com      # basic only
  KESTREL_JIRA_API_TOKEN=***              # API token (Cloud) or PAT (Server/DC)
  KESTREL_JIRA_PROJECT=RFC
  KESTREL_JIRA_JQL_FILTER=status = "Ready for Kestrel"   # optional; AND-ed onto project=RFC
  KESTREL_JIRA_REPO_FIELD=customfield_10050              # holds owner/name[@base_branch]
  KESTREL_JIRA_POLL_INTERVAL_SECONDS=300
  KESTREL_MAX_VERIFY_ITERATIONS=3
  KESTREL_PUBLIC_BASE_URL=https://kestrel.example.com    # for clickable deep-links (optional)

  # Code host for Jira-resolved repos (self-hostable — sovereignty posture):
  KESTREL_CODE_HOST=gitlab                                # github | gitlab | gitea
  KESTREL_CODE_HOST_BASE_URL=https://gitlab.internal.example.com   # self-hosted instance
  KESTREL_CODE_HOST_TOKEN=***                             # PAT for the self-hosted host
  # (KESTREL_CODE_HOST=github falls back to KESTREL_GITHUB_TOKEN / github.com)

  # Verify grounding — project checks run in the isolated worktree as evidence:
  KESTREL_VERIFY_CHECKS=["uv run pytest -q","npm --prefix frontend test"]
  ```

- GitHub-sourced and manual runs continue to use GitHub as their code host; only
  Jira-resolved repos use `KESTREL_CODE_HOST`. Set it to `gitlab`/`gitea` for a fully
  self-hosted, no-external-cloud deployment.

- No inbound endpoint is exposed — polling is outbound-only, so no tunnel/reverse-proxy is
  needed for ingestion (contrast with the GitHub webhook). The public base URL is only for
  clickable deep-links, the posture already recorded in the constitution (v1.2.0).

## Scenario 1 — A Jira RFC starts a run, with repo resolution (US1 / FR-001,006,007)

1. Create/transition an RFC in project `RFC` so it matches the JQL filter, with the repo field
   set to a reachable `owner/name`.
2. Wait one poll cycle.
   **Expect**: exactly one run appears, `source="jira-issue"`, `repo=<resolved>`,
   `task_ref=<issue key>`, and it begins refining. Log line `outcome=started`.
3. Leave the repo field empty on a second RFC; wait a cycle.
   **Expect**: no run; log `outcome=unresolved-repo`; a thin comment on that RFC says the target
   repo could not be determined.
4. Let the same RFC be seen on the next cycle.
   **Expect**: still exactly one run (idempotent — FR-031).

## Scenario 2 — Refinement clarifications & PRD approval via Jira (US2 / FR-009,010,011,013)

1. Drive the run into a clarification round (stub the refine panel to raise one).
   **Expect**: a **thin** comment on the RFC — a deep-link to the kestrel questionnaire only, no
   questions or content. The run holds at `awaiting_refine_input`.
2. Open the deep-link, answer in the kestrel questionnaire, submit.
   **Expect**: refinement resumes; on completion the run reaches `awaiting_refine_approval`, the
   **PRD is attached** to the RFC (`PRD.md`), and a thin comment asks for approval with a
   deep-link.
3. Approve via the linked UI.
   **Expect**: the run enters `designing`.
4. Repeat and **reject** the PRD instead.
   **Expect**: the run does not enter design; it ends `rejected` and a dismissal is recorded for
   the `task_ref`.

## Scenario 3 — Autonomous design → code → verify → change request (US3 / FR-014,015,015a,016,019)

1. From an approved PRD, let the loop run (stub agent backends) with `KESTREL_VERIFY_CHECKS`
   set to a passing command.
   **Expect**: `designing` → `coding` → `verifying` with **no** `awaiting_*` gate entered; the
   configured checks run in the worktree and their results feed the verifier.
2. Force the verifier to reject once, then accept.
   **Expect**: the coder re-runs with the verifier feedback, the verifier re-checks, then a
   change request (a GitLab merge request on the configured self-hosted host, or a GitHub pull
   request) is opened and a comment with the CR link is posted on the RFC; run `done`.
3. Point `KESTREL_VERIFY_CHECKS` at a command that fails on the coder's output.
   **Expect**: the verify round rejects regardless of the model's text (failing-check
   invariant), and the failing check output appears in the coder's next feedback (FR-015a,
   SC-006a).

## Scenario 4 — Verify bound & escalation (US3 / FR-017,018)

1. Force the verifier to reject every round with `KESTREL_MAX_VERIFY_ITERATIONS=2`.
   **Expect**: exactly 2 code↔verify rounds, then the run is `escalated`, **no** change request
   is opened, and one escalation comment is posted on the RFC. The code↔verify loop never
   exceeds the bound.

## Scenario 5 — One unified workflow across sources (US4 / FR-024,025)

1. Start a GitHub-sourced run (label an issue) and a Jira-sourced run.
   **Expect**: both traverse the identical status sequence
   (`refine → awaiting_refine_approval → designing → coding → verifying → opening_pr → done`),
   differing only in the notification surface (GitHub issue comment vs Jira comment) and the
   change-request body (`Closes #n` vs RFC key). GitHub still triggers from a label and opens a
   pull request; the manual "Start workflow" still works, now feeding the same pipeline.

## Scenario 6 — Restart resilience (FR-031,032)

1. Restart kestrel while a run holds at `awaiting_refine_approval`.
   **Expect**: the gate is re-parked; **no** duplicate PRD/approval comment is posted.
2. Restart while a run is `coding` or `verifying`.
   **Expect**: the run is failed loudly (`error="backend restarted mid-step"`); the RFC is not
   re-ingested into a second run on the next poll cycle.

## Automated test suites (Constitution III)

- **Backend** (`cd backend && uv run pytest`): Jira client (search/get/comment/attach/field,
  httpx mocked); repo resolution (resolved / empty / unreachable); source-neutral
  `maybe_start_run` + dismissal + one-run-per-`task_ref`; Jira poll cycle + idempotency;
  reshaped state machine; verify loop (accept / reject-then-accept / exhaust→escalate);
  check runner + evidence (failing check forces reject; failing output in coder feedback);
  `GitLabCodeHost` (merge request, draft prefix, default-branch probe, httpx mocked);
  `TaskSourceNotifier` dispatch + best-effort failure + thin content; `publish_refined`
  routing (update-issue vs attach); migration `0007` up/down + backfill. No real `claude`, Jira,
  or production DB.
- **Frontend** (`cd frontend && npm test`): status/step label + chip-tone maps for
  `designing`/`coding`/`verifying`/`escalated` and `design`/`code`/`verify`; deep-link `?run=`
  still selects a run; HTTP mocked.

## Not validated here (out of scope / deferred)

- A Jira webhook endpoint (poll-only). Code hosts beyond GitHub + one self-hosted git host
  (GitLab reference; Gitea/Forgejo is the same port). The **behavioural verification harness** —
  running the modified project and exercising it via real HTTP requests (APIs) or Playwright
  (GUIs) — is the *assumed* verifier model but its exact implementation is **out of scope for
  this feature** (v1 ships the generic `Observation`/`Evidence` interface + a minimal `check`
  gatherer over `KESTREL_VERIFY_CHECKS`; **Playwright is not added yet**). Richer executable
  acceptance criteria emitted by refinement/design. Ingesting free-text Jira comment replies or
  status transitions as answers/decisions. Multi-repository RFCs.
