# Quickstart: validating the workflow visualisation rework

**Feature**: `specs/029-workflow-visualisation` | **Date**: 2026-09-28

How to run and prove this feature. Shapes and component boundaries are in
[`data-model.md`](./data-model.md) and
[`contracts/routes.md`](./contracts/routes.md) — not repeated here.

## Prerequisites

- Backend dependencies installed (`uv sync` in `backend/`)
- Frontend dependencies installed (`npm install` in `frontend/`)
- `vue-router@^4.6.4` added; `@vue-flow/core` removed (by the end of the feature)
- The four additive DTO fields in place (FR-040–FR-043,
  [`contracts/board-api-additions.md`](./contracts/board-api-additions.md)) — the
  board cannot nest decomposition children or show titles without them, and the
  interview cannot show a round cap
- A fixture task source configured, so the board can be populated without
  touching GitHub or Jira
- **To exercise multi-round interviews, raise `board_refinement_round_cap`** — it
  defaults to `1`, so on a stock config every interview is single-round and the
  round indicator's interesting behaviour (FR-024's "round 3 of 3") never appears

## Run it

```bash
# terminal 1 — backend
cd backend && uv run uvicorn app.main:app --reload

# terminal 2 — frontend
cd frontend && npm run dev
```

The board is the default surface at the dev server's root.

## Seed a board worth looking at

The fixture task source (`visibility() == "private"`, so it is safe to reset)
is the intended way to populate this. A useful fixture set exercises every
treatment the board must distinguish:

| Fixture request | Proves |
| --- | --- |
| One at `Understanding` | Intake & alignment column, early phase position |
| One at `Pre-assessment` awaiting an answer | `your-move` treatment, interview entry point |
| One at `PRD sign-off` | `your-move` with an approve/reject decision |
| One decomposed into children | FR-002 — one card, children nested inside |
| One quarantined at intake | `quarantined` treatment, and that it appears **once** |
| One at its round cap | `cap-reached`, distinct from `your-move` |
| One fully terminal | Done column rather than being dropped |

`backend/app/routers/board_dev.py` provides the dev reset surface for
re-running from a clean state.

## Validate by user story

Each block is independently checkable — matching the spec's prioritisation, so a
partial implementation can still be validated.

### US1 — Stage board (P1)

1. Open the root address. Six columns appear in order: Intake & alignment,
   Discovery, Definition, Planning, Build & deliver, Done.
2. Count the cards. **Exactly one per ingested request** — the quarantined
   request appears once, and the decomposed parent appears once with its children
   listed inside it.
3. Each card names its request by source reference and title, never by a bare
   workflow id.
4. Each card states its phase in words *and* shows a ten-segment position bar.
5. The waiting, cap-reached and quarantined cards are all visibly different from
   each other and from a plain progressing card.
6. Try to drag a card. Nothing happens — stage placement is derived (FR-006).
7. Unplug the mouse. `Tab` reaches every card; `Enter` opens one; every action
   available by pointer is reachable by keyboard (FR-007).
8. Reset to an empty board. An explanatory empty state appears, not six blank
   columns.

### US2 — Request cockpit (P2)

1. Open a mid-pipeline request. The spine shows ten labelled phases, the current
   one highlighted, gate phases marked differently from work phases.
   **This is the R3 legibility gate** — if ten labelled items do not read
   cleanly at a laptop width, switch to the vertical spine fallback. Do not
   hand-write horizontal stepper CSS.
2. The feed lists events oldest-first, each with a persona.
3. Find a workflow-level event or an operator-resolved gate: it is attributed
   **neutrally**, not to a guessed specialist and not to a blank name (FR-013).
4. Let the backend emit a new event while the cockpit is open — it appears with
   no manual refresh. Then scroll back in the feed and let another arrive: the
   view does **not** yank you to the bottom (FR-018).
5. The artifact rail lists the full durable set in pipeline order, including the
   artifacts this request has not produced yet.
6. Open the PRD artifact. Content renders as **text**; its provenance is stated,
   so unreviewed agent output is distinguishable from operator-approved content.
7. Exactly one prominent element states what the request wants from you, and it
   is not duplicated elsewhere on the page.
8. Open a request awaiting nothing: no action prompt at all — not a disabled one.
9. Open a cockpit, then act on a decision from a second tab first. The first
   tab's action is refused with a human "this moved on" message, not a generic
   failure (the 409 `expected_revision` path).

### US3 — Interview workspace (P3)

1. From a waiting request's CTA, reach the interview. It is its **own** surface,
   not a pane inside the cockpit.
2. Questions are grouped under the persona that asked them.
3. Type a partial answer, navigate to the board, come back. The text is still
   there (FR-022).
4. Watch for the draft-saved confirmation — it is clearly distinguishable from
   having submitted (FR-022).
5. On one question choose "I don't know". It records an assumption request, not
   an empty answer.
6. On another choose "not relevant". It stops blocking submission.
7. With a required question still blank, attempt to submit. Refused, and the
   outstanding question is identified (FR-026).
8. On a request at round 3 of 3, the surface says so, and says that this is the
   last chance before assumptions are recorded in the PRD (FR-024).
9. Submit. You land on that request's cockpit and the submission's effect is
   visible there (FR-020).
10. On a single-round interview, the round indicator reads as one round, not as
    an empty progress track (FR-027).

### US4 — Addressability (P4)

1. Copy a cockpit address. Open it in a fresh private window: the cockpit renders
   directly, without the board flashing first.
2. Walk board → cockpit → interview, then press back twice: cockpit, then board.
3. Edit the address to name a request that does not exist: an explanatory message
   and a route back to the board (FR-030) — not a blank page, not a stack trace.
4. Visit `/?run=<a-real-id>`: it resolves to that request's cockpit (FR-031).
   Then press back — you do **not** land back on the redirect.
5. Confirm the bundled image behaves identically: build it and reload a deep
   address. This is the check that research R2 exists for —
   `StaticFiles(html=True)` does **not** fall back to `index.html`, which is why
   addresses are hash-based.

### Backend additions (FR-040–FR-043)

Verifiable before any UI exists:

```bash
cd backend && uv run pytest tests/test_board_api_additions.py
# then, against a running backend with a decomposed fixture request:
curl -s 'localhost:8000/api/board/workflows?include_completed=true' \
  | jq '.[] | {task_label, title, parent: .parent_workflow_id, cap_exhausted}'
```

Expect: `title` distinct from `task_label`; `parent` `null` for a top-level request
and set for a decomposition child. Note the `include_completed=true` — without it
terminal requests are absent and the Done column has nothing to show (FR-044).

### US5 — Retirement (P5)

Only after US1 and US2 are in place and green.

```bash
cd frontend
grep -r "vue-flow\|WorkflowGraph\|boardGraph" src/ tests/   # expect no hits
grep "vue-flow" package.json                                # expect no hits
npm run knip          # no new findings
npm run depcruise     # passes
npm run test          # passes
npm run build         # type-checks and builds
```

## The gate that actually matters

```bash
task quality
```

Must pass before the task is considered done, per `AGENTS.md`. Then, per the
developer's standing instruction, also run the checks `task quality` does *not*
cover before pushing:

```bash
cd frontend && npm run format:check && npm run build && npm run test
cd ../backend && uv run pytest
```

No suppression, threshold edit, or grandfather-list entry may be added to make
any of these pass (FR-035, SC-013). If a limit is genuinely hit, split the module
— and if a limit genuinely seems wrong, stop and ask the developer.
