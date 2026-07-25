# Contract: behavioral verify evidence (extends 003's `verify-evidence.md`)

> **Amendment (2026-07-25)**: `CheckRunner`/`verify_checks` (the deterministic
> shell-check gatherer this contract originally assumed stays "unchanged")
> was **removed entirely**, as a deliberate follow-up decision — not
> mechanical drift. Rationale: blending a technical/structural signal
> (pytest, lint) into the same hard gate as behavioral PRD-conformance
> evidence contradicted the "verify judges like a stakeholder, not a code
> reviewer" principle US2 already established for code-quality feedback; a
> `verify_checks` failure reaching the verifier meant the coder didn't do
> its TDD job (`CODE_PROMPT` already requires it), not that the *behavior*
> was wrong. Verify's evidence is now **entirely** self-reported by the
> verifying agent's own exploration — every `CheckRunner`/`verify_checks`
> reference below is historical (describes what US1 originally shipped),
> not current behavior. Known, accepted trade-off: for `boundary="none"`
> projects there is no evidence source left at all — verify is pure LLM
> self-judgment with no mechanical backstop.

This supersedes the "assumed/deferred" half of
`.specify/specs/003-jira-ingestion/contracts/verify-evidence.md` — the
`Observation`/`Evidence` shapes and the failing-observation invariant it
defined are unchanged and still authoritative; this contract specifies how
`kind="http"`/`"ui"` observations actually get produced.

## Boundary classification contract (`design` → `verify`)

- `DESIGN_PROMPT` requires the designer's final response to include, in
  addition to `<PLAN>...</PLAN>`, a `<BOUNDARY>...</BOUNDARY>` block whose
  content is exactly one of: `http`, `ui`, `both`, `none`.
- `_design()` parses it via `extract_boundary()`; a missing or unparseable
  tag is treated as `none` (never fails the design step).
- The result is stored once as `WorkflowRun.boundary` and is immutable for
  the rest of the run.

## Explore-turn contract (`verify`, the explore turn)

- Runs in a tool-enabling `permission_mode` (see `research.md` R2) in the
  run's worktree (`cwd=run.workspace`), same as every other step.
- Prompt carries: PRD, design, diff, `boundary` (originally also rendered
  `CheckRunner` evidence gathered so far this round — removed, see
  amendment above).
- When `boundary` is `http` or `both`: the agent MUST be instructed to
  launch the modified project and issue real HTTP requests against it.
- When `boundary` is `ui` or `both`: the agent MUST be instructed to launch
  the modified project's dev/preview server and drive it via whatever
  browser-automation tool is available, visually inspecting the result.
- When `boundary` is `none`: the explore turn is skipped entirely — go
  straight to the verdict turn with no prior evidence at all (see
  amendment above), unchanged from today's behavior (FR-003).
- When boundary-appropriate tooling is unavailable to the agent, the prompt
  MUST instruct it to say so explicitly rather than silently skip to
  diff-only judgment (FR-007) — this becomes part of what the verdict turn is
  told to surface in `feedback`.
- No required output format on this turn — it is free-form exploration.

## Verdict-turn contract (`verify`, the verdict turn)

- Resumes the **same session** as the explore turn (`resume_id` = the explore turn's session id).
- Switches `permission_mode` back to `"plan"`, no new tools.
- Prompt is narrow: "given what you just observed, respond with ONLY the
  verdict JSON" (see `data-model.md` for the extended shape). This is the
  only turn `_parse_verdict` reads from.
- `_parse_verdict` (extended) returns `(accept, feedback, observations)`.
  Malformed/missing `observations` → treated as empty, never a parse
  failure on its own (only a fully unparseable verdict block is a parse
  failure, exactly as today).

## Merge & invariant contract (originally "unchanged from 003" — `CheckRunner`
## side removed per the amendment above; the invariant itself is unchanged)

1. ~~`evidence = CheckRunner` results.~~ `evidence = Evidence()` (empty).
2. `evidence.observations += [Observation(**o) for o in verdict.observations]`
   (defensively — drop malformed entries, never raise).
3. `if not evidence.all_passed(): accept = False` — applies to the (now
   entirely self-reported) list, so a self-reported http/ui failure forces
   rejection regardless of what `verdict.accept` said.

## Audit-trail contract

- One `verify-report.md` per run, written via `_write_artifact`, same
  handover-artifact lifecycle as `prd.md`/`design.md` (committed with the
  change, excluded from the diff the verifier weighs).
- Read by: nobody, programmatically. It is human-facing history only — no
  code path in this or any later run loads it back as verify input
  (FR-009).

## Test contract

- `extract_boundary` returns each of the four valid values, and `None` for a
  missing/malformed tag (mirrors existing `extract_plan` test coverage
  style).
- `_parse_verdict` (extended) still accepts a verdict with no `observations`
  key exactly as it does today — no regression on existing
  `test_verify_loop.py` cases.
- A verdict whose `observations` contains one `passed: false` entry forces
  `accept=False` even when the verdict's own `accept` field says `true`
  (`test_self_reported_observation_failure_forces_reject`).
- When `boundary="none"`, the explore turn is never dispatched —
  assert on call count / mock invocation, not just on the final verdict.
- `verify-report.md` exists after a run reaches `done` or `escalated`, and
  its content is not read by any subsequent verify round (a second run
  against the same repo must not have its verdict influenced by it — no
  test should need to delete it between runs for the second run to pass).
