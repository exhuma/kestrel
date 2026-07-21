# Contract: Gate Notification (GitHub issue comment)

Composes with the existing in-app notifier at the single `_save()` choke point
(`services/workflows.py:336-356`). No run-execution call site changes.

## Notifier protocol (unchanged, synchronous)

`Notifier.notify(run: WorkflowRun) -> None` (`notifications.py:96-101`). Stays sync
so `_save()` remains cheap and never blocks the driver / webhook ACK (FR-005).

## `CompositeNotifier(notifiers: list[Notifier])`

- `notify(run)` calls each child in order. `InAppNotifier` first (always records a
  row — the durable fallback), then `GitHubIssueNotifier`.
- A child raising must not stop the others (defensive — a GitHub notifier bug can't
  suppress the in-app record).
- Wired in the service factory replacing the bare `InAppNotifier`
  (`services/workflows.py:1536-1538`).

## `GitHubIssueNotifier(github, settings, ...)`

`notify(run)`:
1. If `run.status` is not an `awaiting_*` gate → return (do nothing). All gates
   (input **and** approval) qualify (clarification Q1: "All gates"). Terminal
   `done`/`failed` are handled by the in-app notifier only — GitHub comments are for
   attention gates.
2. Build body = `render_message(run)` (reused templates, `notifications.py:68-79`)
   + a deep-link line when `settings.public_base_url` is set (see `deep-link.md`);
   otherwise the body alone (link-less — clarification Q3 / FR-024).
3. Schedule the POST fire-and-forget:
   `asyncio.create_task(self._post(run.repo, run.issue_number, body))`, where
   `_post` calls `github.create_issue_comment(...)` inside try/except that logs
   failures and swallows them (FR-026). The run is never blocked or failed by a
   posting error; the in-app row already exists (FR-026/SC-010).

## Behavioural guarantees

- **One comment per genuine gate entry** (FR-025): each `awaiting_*` transition
  through `_save()` posts once. Successive refine rounds each bump `refine_round`
  and re-enter the input gate via `_save()`, so each round posts its own comment
  with its own link.
- **Restart-idempotent** (FR-030, R-07): recovered gates re-park **without**
  `_save()`, so no comment is re-posted after a restart. A guard test pins this
  invariant.
- **No content leak** (FR-031): body is template + link only; never refined
  description, plan, or questionnaire text. No secret/token/signature (FR-006/FR-029).

## Message templates (reused, `notifications.py:42-61`)

| Run status | Body (before the link line) |
|------------|------------------------------|
| `awaiting_refine_input` | "Kestrel needs your input refining {repo}#{issue}." |
| `awaiting_refine_approval` | "Refined description ready for review: {repo}#{issue}." |
| `awaiting_plan_approval` | "Implementation plan ready for review: {repo}#{issue}." |
| `awaiting_implement_input` | "Kestrel needs your input during implementation: {repo}#{issue}." |
| `awaiting_implement_approval` | "Implementation ready for review: {repo}#{issue}." |

## Test contract

- each `awaiting_*` status → `create_issue_comment` called once with the templated
  body; with `public_base_url` set the body ends with the deep-link, unset ⇒ no link.
- `create_issue_comment` raising → logged, swallowed; the run still reaches/holds its
  gate and the in-app row exists (SC-010).
- `done`/`failed`/`rejected` → GitHub notifier posts nothing.
- recovery re-entering a gate (no `_save`) → no comment posted (R-07 guard).
