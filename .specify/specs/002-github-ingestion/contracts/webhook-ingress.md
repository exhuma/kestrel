# Contract: Webhook Ingress

**Endpoint**: `POST /api/github/webhook` (new router `app/routers/github_webhook.py`,
registered in `main.py` before the SPA static mount). This is the **only** endpoint
intended to be reachable off-loopback; every other route stays loopback-bound.

## Request (from GitHub)

Headers:
- `X-GitHub-Event` — event type; only `issues` is handled, others are acknowledged
  and ignored.
- `X-GitHub-Delivery` — delivery UUID; the dedup key.
- `X-Hub-Signature-256` — `sha256=<hex>` HMAC of the raw body under `webhook_secret`.
- `Content-Type: application/json`.

Body: GitHub `issues` event payload. Fields used: `action` (`labeled` starts a run;
`unlabeled` clears a dismissal), `label.name` (must equal `trigger_label`),
`repository.full_name` (`owner/name`, must be in `watched_repos`), `issue.number`,
`issue.title`.

## Verification & handling order

1. Read **raw** body bytes.
2. Compute `hmac.new(webhook_secret, raw, sha256)`; compare to the header with
   `hmac.compare_digest` (FR-002/FR-003). Missing header or mismatch →
   **`401`**, outcome `rejected-signature`, no run (FR-002). The secret/signature
   are never logged (FR-006).
3. `WebhookDeliveryStore.seen(delivery_id)` — if already present → **`200`**,
   outcome `duplicate`, no run (FR-004).
4. If event = `issues` and action = `unlabeled` for the `trigger_label` on a watched
   repo → clear any dismissal for `(repo, issue)` (FR-008a) and **`200`**, outcome
   `ignored` (no run). This lets a re-added label start fresh.
5. If event ≠ `issues`, action ≠ `labeled`, label ≠ `trigger_label`, or repo ∉
   `watched_repos` → **`200`**, outcome `ignored`, no run (FR-011).
6. If the `(repo, issue)` is **dismissed** (`DismissalStore.is_dismissed`) → **`200`**,
   outcome `ignored`, no run (FR-008a).
7. Otherwise dispatch `ingestion.maybe_start_run(repo, issue_number,
   source="github-issue")` as a background task and **return `202` immediately**
   (FR-005 — ACK does not block on run creation). Outcome `run-started` (or
   `duplicate` if the one-run-per-issue guard rejects it; `run-failed` if the start
   raises before a run row persists — recorded, leaves no run record or dismissal so
   reconciliation retries per FR-013a).

## Responses

| Status | Meaning |
|--------|---------|
| `202 Accepted` | Authentic, qualifying — run creation dispatched |
| `200 OK` | Authentic but duplicate/ignored/non-triggering (stops GitHub retrying) |
| `401 Unauthorized` | Missing/invalid signature |
| `400 Bad Request` | Unparseable body / missing required headers (acknowledged as a client error; no crash — Edge Cases) |

Malformed-but-signed payloads and unhandled event types never error the service
(Edge Cases); they return `200`/`400` and record an outcome.

## Structured log line (FR-021)

Every delivery logs one structured record: `delivery_id`, `event`, `action`,
`repo`, `issue_number`, `outcome` ∈ {accepted/run-started, rejected-signature,
duplicate, ignored, run-failed}. Never the secret, signature, or token (SC-007).

## Test contract

- valid signature + `labeled` + trigger label + watched repo → `202`, exactly one
  run created; same delivery again → `200`, still one run.
- tampered body / wrong secret / missing header → `401`, zero runs.
- `labeled` with a non-trigger label, or watched-repo miss → `200`, zero runs.
- non-`issues` event → `200`, zero runs.
- `labeled` for a **dismissed** `(repo, issue)` → `200`, zero runs (FR-008a).
- `unlabeled` (trigger label) for a dismissed issue → dismissal cleared; a later
  `labeled` then starts a fresh run (FR-008a).
- start raises before a run row persists (issue gone) → outcome `run-failed`; no
  run record and no dismissal remain, so reconciliation re-attempts later
  (FR-013a).
