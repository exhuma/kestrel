# Contract: verification evidence & the evidence gatherer

Grounds the verifier in the **observed behaviour of the running, modified project** (FR-015a,
FR-015b, SC-006a, R-06). New shapes in `backend/app/ports.py`; the v1 interim gatherer in
`backend/app/services/checks.py`.

## Assumed verification model (design-level; harness delivered incrementally)

The design **assumes** the verifier runs the modified project in the isolated worktree and
exercises its real boundary, then adjudicates the observed behaviour against the PRD:

- **HTTP API** (e.g. FastAPI) — launch the app, issue **real HTTP requests**, assert on responses
  → `Observation(kind="http", …)`.
- **Web GUI** (e.g. a Vite app) — launch the dev/preview server, **drive via Playwright** and
  visually inspect → `Observation(kind="ui", …)`.
- Other boundaries are edge cases → fall back to configured checks / model judgment.

The **exact behavioural harness** (project launch, request/interaction scripting, browser
automation, boundary detection) is **NOT required in full by this feature** and may be delivered
incrementally; this contract carries its output so later delivery does not reshape the workflow.

## Shapes (`ports.py`)

- `Observation(name: str, kind: Literal["http","ui","check"], passed: bool, detail: str)` — one
  observed outcome. `detail` is a bounded excerpt (an HTTP request/response summary, a UI
  interaction/assertion or screenshot ref, or a check's output tail — never full logs, no secrets).
- `Evidence(observations: list[Observation])` — the evidence bundle for one verify round. Empty
  when no gatherer produced observations. In-memory only; a compact summary lands in the `verify`
  step's `deliverable`.

## Evidence gatherers

- **v1 interim** — `CheckRunner.run(workspace) -> Evidence` (`services/checks.py`): runs each
  `settings.verify_checks` command in the worktree cwd (existing subprocess helper, bounded
  timeout), mapping exit code → `passed`, emitting `Observation(kind="check", …)`. `Evidence([])`
  when unconfigured.
- **Assumed/deferred** — a behavioural harness producing `kind="http"`/`kind="ui"` observations by
  running and exercising the app. Same `Evidence` return type; drops in without workflow change.

## Verify phase integration (`services/workflows.py`)

1. After `code` produces a diff, the driver gathers `Evidence` (v1: `CheckRunner`; later: the
   behavioural harness).
2. `VERIFY_PROMPT` is rendered with the PRD, the design deliverable, the diff, **and the
   evidence** (each observation's name + kind + pass/fail + detail).
3. The `verifier` agent adjudicates and emits `<VERDICT>{ "accept": bool, "feedback": str }</VERDICT>`.
4. **Invariant**: any failing `Observation` MUST NOT be reconciled with `accept: true` — if any
   observation failed, the round is a rejection regardless of the model's text.
5. On rejection, the coder's feedback prompt includes the failing observations' `detail`.

## Boundaries (v1)

- v1 ships the **`Observation`/`Evidence` interface + the invariant + a minimal `check` gatherer**.
  The behavioural HTTP/Playwright harness and boundary detection are **designed-for but deferred**;
  richer executable acceptance criteria emitted by refinement/design are also deferred.
- Playwright is an **assumed future dependency** for the GUI harness; it is **not added** by this
  feature.
- No persistence: evidence lives on the driver's `_Control` for the round; a restart mid-verify
  fails the run loudly like any transient state.

## Test contract

- `CheckRunner.run` executes each configured command in the worktree cwd, maps exit code →
  `passed`, bounds `detail`, and returns `Evidence([])` when unconfigured (subprocess mocked).
- A failing observation ⇒ the verify round rejects even if the model text says accept (invariant §4).
- Failing observation `detail` appears in the coder's next feedback prompt.
- No secret/token appears in any `detail` or log line.
