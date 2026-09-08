# Contract: triage → re-entry → branch resume

Covers spec.md FR-008 through FR-013 (User Stories 3 and 4).

## Triage turn (`services/feedback/triage.py`, prompt in `prompts_feedback.py`)

Runs once per dispatched feedback item that reaches this path (terminal-run
or review-origin feedback, per `feedback-dispatch.md`'s routing table).
Inputs: the feedback body, `steps[0]` (Understanding), `steps[1]` (PRD),
`steps[3]` (Design) deliverables, and — for review-origin feedback — the
PR's diffstat. Output, house style (matching every other structured-turn
prompt in `prompts.py`):

```
<TRIAGE>{"step": "code", "reason": "...", "instruction": "..."}</TRIAGE>
```

Parsed by `extract_feedback_triage()` (`services/workflow_text.py`, next to
`extract_containment_verdicts`). `step` MUST be one of `describe`, `refine`,
`gap_analysis`, `design`, `code`. A parse failure or unrecognized value
defaults to `code` and logs a warning — never fails the dispatch outright.
`instruction` is a **normalized restatement** of the feedback, never the raw
comment body — this is what actually reaches the target step's prompt
(FR-009: kestrel decides which point the feedback concerns; the step itself
still only ever sees a clean instruction, the same shape `describe()`/
`refine()`'s existing feedback-loops already expect).

`decomposed` runs never reach this turn — `FeedbackDispatcher` routes them
to `publish_correction()` directly (`feedback-dispatch.md`'s table), so no
triage step selection is possible for them (FR-013).

## Re-entry (`services/workflows/reentry.py::rewind_to`)

```python
def rewind_to(run: WorkflowRun, step: Step, instruction: str) -> None
```

Pure function (no I/O, no persistence — caller saves). Generalizes
`_seed_from_sentinel`'s existing pre-mark trick (`driver/__init__.py`) to an
arbitrary target step:

- Every step **before** the target: `status = "done"`, deliverable
  untouched (preserved).
- The **target** step: `status = "pending"`.
- Every step **after** the target: `status = "pending"`, `session_id =
  None` (no stale resume-id survives into a step that hasn't actually run
  yet in this cycle).
- `run.verify_round` reset to 0.

`instruction` is threaded through to whichever prompt the target step
normally consumes feedback via — `DESCRIBE_FEEDBACK_PROMPT` for `describe`,
`interview.rewrite_refined` for `refine`, `CODE_FEEDBACK_PROMPT`'s existing
`feedback` slot for `code`. No new prompt-consumption path is needed for
`describe`/`refine`/`code`; only `gap_analysis`/`design` need a feedback
slot added to their existing prompts (small, additive change — no existing
call site's signature changes shape, only gains an optional parameter).

After `rewind_to`: fresh `_Control` (`service._new_control()`), `run.status
= "pending"`, `service._save(run)`, `service._spawn_driver(run.id,
resume.resume_with_feedback(service, run.id))`.

## Revive vs. successor (`services/feedback/dispatch.py`, terminal-run branch)

```
done + get_change_request(...).state == "open"      → revive (this run)
done + get_change_request(...).state in {merged, closed} → linked successor
escalated                                             → revive (this run)
decomposed                                            → publish_correction() (no revive, no successor)
```

- **Revive** (`done`, open PR): `driver/resume.py` — `ensure_mirror` (refetch
  so a human's own commits on the PR branch are pulled in) → `git.
  add_worktree_existing(mirror_dir, workspace, run.branch)` → `
  _ensure_artifact_dir` → `rewind_to(run, triaged_step, instruction)` →
  `continue_run`. `deliver()` becomes idempotent for this path: when
  `run.pr_number` is already set and the PR is still open, it pushes only —
  **no** second `open_change_request` call — and posts exactly one "Updated
  the change request: …" comment (the only landing comment FR-015 permits
  for this path).
- **Linked successor** (`done`, PR merged/closed): `IngestionService.
  maybe_start_run` — reused exactly as-is, with the new run's body/metadata
  carrying the parent run's id (`Run lineage`, data-model.md), so the two
  are never mistaken for unrelated activity on the same ticket (FR-011,
  Key Entities).
- **Revive** (`escalated`): no PR exists yet at this point (escalation never
  pushes), so there's nothing to resume *onto* — `driver/resume.py` falls
  back to today's `add_worktree` (fresh branch off `base_branch`) rather
  than `add_worktree_existing`, then proceeds the same way (`rewind_to` →
  `continue_run`), carrying the triage instruction into the retry (FR-012:
  "starting from the last point it has a usable foundation to build on" —
  the base branch, since that's genuinely the last durable foundation an
  escalated run has).
- **Correction** (`decomposed`): single-shot `publish_correction()` — calls
  `TaskSource.create_subtask` once with the triage-derived correction
  content; duplicate-safe the same way every other feedback action is
  (`feedback_item.external_id` primary key prevents the same feedback from
  ever producing two corrections).

## Branch resume (`services/git.py::add_worktree_existing`)

```python
async def add_worktree_existing(
    self, mirror_dir: str, dest: str, branch: str
) -> None
```

`git -C <mirror> worktree add <dest> <branch>` when the mirror already
holds the local ref (the common case, since `deliver()` keeps the branch
after tearing down the worktree). Falls back to `worktree add -b <branch>
<dest> origin/<branch>` (after a refetch) when the mirror's local ref is
gone. Shares a private `_worktree_add` helper with the existing
`add_worktree` so the `user.email`/`user.name` identity-setting lines are
not duplicated (this repo's jscpd copy-paste budget is thin — 2.94% of a 3%
gate as of the prior branch).

## Test contract

- `rewind_to` is tested per legal target step: confirms exact before/target/
  after status partitioning, confirms `session_id` is cleared only for
  steps *after* the target, confirms deliverables before the target
  survive untouched.
- `extract_feedback_triage` is tested for a well-formed tag, a malformed
  tag (falls back to `code` + logs), and an unrecognized `step` value (same
  fallback).
- A `done` run with an open PR + review feedback → same branch resumed
  (`add_worktree_existing` called, not `add_worktree`), `deliver()`'s
  second pass pushes without a second `open_change_request` call, exactly
  one landing comment posted.
- A `done` run with a merged PR + review feedback → `maybe_start_run`
  called for a successor; the successor's stored lineage points at the
  original run's id.
- An `escalated` run + feedback → `add_worktree` (fresh, base-branch) is
  used, not `add_worktree_existing`.
- A `decomposed` run + feedback → `create_subtask` called exactly once via
  `publish_correction`; `run_gap_analysis` is never invoked.
