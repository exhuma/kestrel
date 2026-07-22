# Contract: Gate Deep-Link

A stable URL in each gate comment that opens the kestrel UI on the run and its
active gate form.

## URL format

```
{public_base_url}/?run={run_id}
```

- `public_base_url` — backend setting `KESTREL_PUBLIC_BASE_URL` (trailing slash
  tolerated/normalised). Unset ⇒ **no link** is emitted (link-less comment, FR-024).
- `run_id` — the durable run id (`wf-<hex8>`), so the link resolves the same run
  after a restart (FR-027).
- Built **server-side** in `GitHubIssueNotifier`; the SPA needs no new build-time
  env var.

Comment link line (only when `public_base_url` set):
`Open in kestrel: {public_base_url}/?run={run_id}`

## Frontend entry (deep-linking)

There is no router today; the entry is minimal (R-08):

1. `main.ts` on load reads `new URLSearchParams(window.location.search).get('run')`.
2. If present, call the singleton `useWorkflows().select(runId)`
   (`composables/useWorkflows.ts:65`). `select()` works from a bare id: it opens the
   run's SSE stream and sets `current`, which drives `WorkflowPanel.vue`.
3. The active gate form is **derived** from the run's step state
   (`WorkflowPanel.vue:57-67`: first step in `running`/`awaiting_input`/
   `awaiting_approval` → questionnaire vs approve/reject form). Selecting the run is
   therefore sufficient to land the maintainer on the correct form (FR-028) — no
   gate identifier is encoded in the URL.
4. The app defaults to the `workflows` view (`App.vue:38`); if a `run` param is
   present, ensure that view is shown.

Optional polish (not required): reflect the current selection back into the URL via
`history.replaceState` in the existing `select` click path so a copied URL deep-links
too.

## Auth interaction

The deep-link lands on the UI, which is protected by the project's shared-secret
access gate (constitution — "shared-secret gate only"). The link carries **no**
secret (FR-029); the maintainer authenticates as normal, and the `run` param
survives that step so they arrive on the intended form.

## Constraints

- No `vue-router`, no Vite `base` change, no dev-server rewrite (query param on
  root — R-08).
- Stable across restarts (keyed by durable `run_id` — FR-027).

## Test contract

- backend deep-link builder: `public_base_url` set → correct `/?run=<id>` string;
  unset → empty (notifier emits link-less body).
- frontend: loading `/?run=<id>` calls `select('<id>')` once and shows the workflows
  view; no `run` param → no `select` call, normal empty state.
- no type-contract change: `source` stays backend-only (clarification Q3), so
  `frontend/src/types/workflows.ts` is unchanged.
