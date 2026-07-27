# Research: Behavioral Verify Evidence

## R1. How does the verify step get real tool access without losing reliable verdict extraction?

**Decision**: Two turns on one resumed session within `_code_and_verify`. Turn A
("explore") runs with a tool-enabling `permission_mode` and a loose prompt
("launch and exercise the project's boundary, then describe what you found —
no required output format"). Turn B ("verdict") resumes the same session with
`permission_mode="plan"` (today's mode) and a narrow prompt ("given what you
just observed, respond with ONLY the verdict JSON"), reusing the existing
`_parse_verdict` discipline unchanged.

**Rationale**: `workflows.py`'s existing inline comment on the verify turn
records a real prior finding: giving verify *any* tool round-trip (even a
read-only one, to fetch PRD/design via file pointers instead of inline text)
measurably hurt reliable `<VERDICT>` emission — which is why PRD/design are
inlined into the prompt today instead of handed as file references. That
finding must be respected rather than re-litigated informally: the verdict
turn keeps zero new tool calls, matching the exact condition under which
`_parse_verdict` is already proven reliable (`test_verify_loop.py`).

**Alternatives considered**:
- *Single tool-enabled turn emitting both narrative and verdict.* Simpler
  (one `run_turn` call, no resume), but reopens exactly the failure mode the
  existing code comment documents. Rejected as the default; noted in the plan
  as a valid simplification to revisit only if the two-turn approach turns
  out to be unnecessary in practice.
- *Fully agentic verify (no separate verdict turn; parse whatever the last
  tool-using message contains).* Rejected — no discipline to fall back on
  when the model's last message isn't cleanly parseable; would need a new
  reject-on-parse-failure retry loop that doesn't exist today.

## R2. What `permission_mode` value should the explore turn use?

**Decision**: `"bypassPermissions"` — the same category of unattended,
non-interactive auto-approval the coder step already depends on (via
`"acceptEdits"`) to run headlessly (`-p`, no TTY) with no human present to
approve a tool prompt. The explore turn needs Bash and MCP tool execution
approved without a prompt, which is a broader ask than `"acceptEdits"`
covers (that mode is documented in this codebase as auto-accepting edits,
not general tool execution).

**Rationale**: Kestrel always runs every step headless (`claude -p ...`,
`--output-format stream-json`, no interactive terminal — see
`services/runner.py::build_argv`). Any permission mode that can leave a tool
call waiting on human approval will hang the run. `"plan"` already guarantees
this for read-only tools (used today by `refine`/`design`/verify's verdict
turn); the explore turn needs the equivalent guarantee extended to
Bash/MCP execution.

**Alternatives considered**: `"acceptEdits"` (same mode as coder) — rejected
as the primary choice because its documented scope is file edits, not
general Bash/MCP tool execution; may prove sufficient in testing, in which
case it's a strict simplification (no new mode string introduced). This must
be validated empirically against the actual `claude` CLI during
implementation — the plan flags it as an implementation-time check, not a
design assumption to build further logic on.

## R3. How does design communicate the boundary classification to verify?

**Decision**: Extend `DESIGN_PROMPT` to require a second delimiter block,
`<BOUNDARY>http|ui|both|none</BOUNDARY>`, alongside the existing
`<PLAN>...</PLAN>`. Add `extract_boundary(text) -> str | None` to
`app/services/workflow_text.py`, following the exact existing pattern of
`extract_plan`/`extract_refined_issue` (both one-line wrappers around the
shared `_extract_tag(text, tag)` helper). Parsed once in `_design()`, stored
on `WorkflowRun.boundary`.

**Rationale**: Zero new parsing mechanism — reuses a helper this module
already has three call sites for. Keeps boundary classification a
first-class, typed run field rather than free text buried in the design
deliverable.

**Alternatives considered**: Parsing the boundary out of the design
deliverable's prose. Rejected — brittle, and the delimiter-tag convention is
already the established idiom for every other step in this codebase
(`<PLAN>`, `<VERDICT>`, `<REFINED_ISSUE>`, `<PROFILES>`).

## R4. Where does `boundary` live in the persistence layer?

**Decision**: A new nullable `TEXT` column on `WorkflowRunRow`
(`backend/app/persistence/tables.py`) and a matching `boundary: str | None`
field on the `WorkflowRun` dataclass (`backend/app/models_workflow.py`),
written through by the existing `WorkflowStore.save()` on every state
transition — the same mechanism every other run field already uses. One new
Alembic migration, following the shape of
`backend/alembic/versions/0009_workflow_step_verify_round.py` (which added
`verify_round` the same way).

**Rationale**: No new storage mechanism; Principle II (Alembic owns schema)
is satisfied the same way the last comparable field addition was.

**Alternatives considered**: An in-memory-only field on the driver's
`_Control` (matching how `Evidence` itself is documented as "in-memory only"
per the 003 verify-evidence contract). Rejected — `boundary` must survive a
process restart mid-run (the recovery/resume path in `_resume()` rehydrates
from `WorkflowStore`), whereas `Evidence` is legitimately scoped to a single
in-flight verify round and does not need to.

## R5. How do self-reported http/ui observations merge with `CheckRunner`'s deterministic ones?

**Decision**: Grow the verdict JSON schema with an optional `observations`
array, each entry matching the existing `Observation` shape
(`name`, `kind`, `passed`, `detail`). After `_parse_verdict` (renamed/extended
to also return these), kestrel constructs `Observation(kind="http"/"ui", ...)`
instances from that array and appends them to the same `Evidence.observations`
list already populated by `CheckRunner`, before evaluating
`evidence.all_passed()`. No change to `Observation`/`Evidence` themselves
(`ports.py`) — the 003 contract already shaped them for exactly this.

**Rationale**: The failing-observation invariant
(`if not evidence.all_passed(): accept = False`) is pure list logic over
`Evidence.observations` — it does not care which gatherer produced an entry.
Merging self-reported entries into the same list means the invariant applies
uniformly with no new branching.

**Bound self-reported `detail` the same way `CheckRunner` already bounds
command output** (`_MAX_DETAIL = 2000` in `checks.py`) — apply the identical
cap when parsing self-reported observations, so a verbose narrative can't
blow past what a committed audit-trail artifact or a future UI surface
should reasonably hold, and so no secret an explored request/response might
contain gets fully echoed into a committed file.

**Alternatives considered**: Keep self-reported findings only as prose inside
`feedback`, never as structured `Observation`s. Rejected — loses the
uniform invariant enforcement (a self-reported failure could then be
"reconciled" away by favorable verdict text, which is exactly the framing
the existing invariant exists to prevent).

## R6. Coder TDD instruction

**Decision**: Extend `CODE_PROMPT` with an explicit instruction to practice
test-first development and include unit/integration tests appropriate to the
change as part of "done," before the diff is considered complete.

**Rationale**: `CODE_PROMPT` currently says nothing about tests at all, yet
`verify_checks` (typically `uv run pytest -q` / `vitest run`) already assumes
a test suite exists and is being maintained. This is a prompt-only change —
no new mechanism, no new config.

**Alternatives considered**: A separate, dedicated "test" step in the
pipeline. Rejected as disproportionate — would change `Step.sequence()` and
every place that assumes exactly four steps (`STEPS` in the frontend,
`Step.sequence()` tests), for a change that a prompt addition already
achieves.
