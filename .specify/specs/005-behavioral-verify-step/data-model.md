# Data Model: Behavioral Verify Evidence

## `WorkflowRun.boundary` (new field)

- **Type**: `str | None`
- **Values**: `"http"`, `"ui"`, `"both"`, `"none"`, or `None` (design step has
  not run yet, or emitted no parseable `<BOUNDARY>` tag).
- **Set by**: `_design()`, parsed via `extract_boundary(result.final_text)`
  from the design turn's `<BOUNDARY>...</BOUNDARY>` tag. Set once per run and
  never changes afterward (design runs exactly once per run).
- **Read by**: `_code_and_verify()`, interpolated into `VERIFY_PROMPT` for
  every verify round of the run.
- **Persistence**: mirrored on `WorkflowRunRow` as a nullable `TEXT` column,
  written through by the existing `WorkflowStore.save()` write-through on
  every state transition (no new persistence codepath). New Alembic
  migration adds the column.
- **Validation**: if `extract_boundary` returns a value outside the four
  known values (or `None`), treat it the same as `None`/`"none"` — falls back
  to today's check+diff-judgment-only verify behavior (FR-003). Never blocks
  the design step from completing; boundary classification failure is not a
  design-step failure mode.

## `Observation` (existing shape, reused — `app/ports.py`, unchanged)

- `name: str`, `kind: Literal["http", "ui", "check"]`, `passed: bool`,
  `detail: str = ""`.
- No shape change. This feature is the first to actually produce
  `kind="http"`/`kind="ui"` instances (previously only `kind="check"` was
  ever constructed, by `CheckRunner`).
- New instances of `kind="http"`/`"ui"` are constructed from the verifier's
  self-reported `observations` array (see Verdict JSON below), each `detail`
  truncated to the same `_MAX_DETAIL` (2000 chars) bound `CheckRunner`
  already applies to command output, for consistency and to keep any
  accidentally-echoed secret from landing whole in a committed artifact.

## `Evidence` (existing shape, reused — `app/ports.py`, unchanged)

- `observations: list[Observation]`.
- Per verify round, now populated from **two** sources merged into one list:
  1. `CheckRunner.run(workspace)` — deterministic, `kind="check"`, unchanged.
  2. The verifier's self-reported `observations` array from its verdict JSON
     — `kind="http"`/`"ui"`, new.
- `all_passed()`/`failures()` behavior unchanged; the failing-observation
  invariant already implemented in `_code_and_verify` applies uniformly
  across both sources since it only ever inspects the merged list.

## Verdict JSON (verify's structured output — extended)

Current shape (`_parse_verdict`, parsed from `<VERDICT>...</VERDICT>`):

```json
{ "accept": true, "feedback": "..." }
```

Extended shape:

```json
{
  "accept": true,
  "feedback": "...",
  "observations": [
    { "name": "GET /items happy path", "kind": "http", "passed": true, "detail": "200 OK, 3 items returned" },
    { "name": "login flow", "kind": "ui", "passed": false, "detail": "clicking Submit left the spinner running; no redirect to /dashboard after 10s" }
  ]
}
```

- `observations` is **optional** — absent or empty is valid (mirrors
  `boundary="none"`, or a boundary the operator's tooling couldn't exercise;
  see FR-003/FR-007). `_parse_verdict` must not require it, and existing
  tests that construct a bare `{"accept": ..., "feedback": ...}` verdict
  (`test_verify_loop.py::_verdict`) must keep passing unchanged.
- Parsed defensively: an entry missing `kind`/`passed`/malformed is dropped
  (logged), never raises — consistent with the existing "reject-on-parse-
  failure is the safe default, but don't crash the loop" posture of
  `_parse_verdict`.

## Verify Record / audit-trail artifact (new)

- **Location**: `.kestrel/<date>-<serial>/verify-report.md`, written via the
  existing `_write_artifact(run, name, content)` helper — same mechanism as
  `prd.md`/`design.md`, same commit-with-the-change lifecycle, same exclusion
  from the diff the verifier itself weighs (`_ARTIFACT_ROOT` exclusion).
- **Content**: per verify round — round number, boundary classification,
  accept/reject, feedback, and the rendered observation list (reusing
  whatever rendering `_render_evidence`/similar already produces for the
  prompt, so there is exactly one formatting function for "evidence as
  text").
- **Written**: once per run, after the code↔verify loop concludes (accept or
  escalate) — appending each round's summary as it completes is acceptable
  too; either satisfies FR-008. Not written mid-round.
- **Lifecycle**: purely additive history. Never read back by any later
  verify round of *any* run (FR-009) — no code path loads a prior
  `verify-report.md` as input to a verdict.
