# Reconciler as a consolidating rewriter — design

## Problem

The refinement interview fans out to stakeholder **profiles**, each an
agent that independently proposes clarifying questions. A reconciler pass
(`WorkflowService._reconcile_questions`) runs after the fan-out to remove
overlaps. In its first form the reconciler could only **delete** a
near-verbatim duplicate id (`extract_kept_ids` returned a keep-list) and
was told to keep "the most authoritative owner".

That is too weak. In a live run three specialists asked essentially the
same question with different framings, e.g.:

- **Product:** "How should user accounts be created?" (scope / acceptance
  framing)
- **Eng:** "How are user accounts created — is this open self-registration
  or a fixed/seeded set of users?" (signup-flow / password-UI framing)

These overlap on the same underlying *fact* (self-service signup vs. a
fixed/seeded set) but read as different questions, so the delete-only
reconciler — with an ambiguous "authoritative owner" for a cross-cutting
scoping fact — kept both. It had no power to **fold** or **simplify**.

Goal: optimise for the **fewest, simplest** questions without losing
decision-relevant detail. Overlapping questions should be folded into one,
phrased for the single specialist whose domain owns them, and
**Product/requester questions must be the plainest of all**.

## Approach

Promote the reconciler from a delete-only filter to a **consolidating
rewriter**: it authors a fresh, minimal question set. This is the most
flexible option (true folding, re-phrasing, re-scoping) and therefore
leans hard on validation-with-fallback so it can only ever *improve* the
pool, never corrupt it.

## Changes

### 1. Contract — fresh questionnaire, not a keep-list
- **Delete** `extract_kept_ids` (`workflow_text.py`) and its tests. The
  id-list contract is gone.
- The reconciler now emits the **same** `<QUESTIONS>{"questions": [...]}`
  shape the generators produce, parsed and schema-validated by the
  existing `extract_questionnaire` / `parse_questionnaire_json`.

### 2. `RECONCILE_PROMPT` (rewrite)
Hand the reconciler the full pooled questions as JSON — `id`, `audience`,
`prompt`, `why`, **`type`, `options`**, `required`, `waiver_label` — plus
`roster_summary()`. Instruct it to:
- Fold every group asking essentially the **same fact** into **one**
  question; state that overlap counts **even when framings differ across
  domains**, using the accounts example as the illustration.
- Assign each output question to the **single** specialist whose domain
  best owns it (its `audience`, chosen from the input audiences).
- Minimise count and phrase as simply as possible **without dropping any
  detail that changes the answer** (justification is not detail).
- Make **requester/Product** questions the **plainest and least
  technical** of all.
- Output only a `<QUESTIONS>` block.

Reinforce the "plainest question" principle in the **requester** persona
(`profiles.py`) so it is shaped at generation time too.

### 3. `_reconcile_questions` (rewrite)
- Show the `reconciler` chip, send the full-fidelity payload, run the
  agent, parse with `extract_questionnaire`.
- **Fallback to the untouched pool** (reconciliation only trims/simplifies,
  never blanks or corrupts) when any of:
  - output absent / malformed / not schema-valid → `None`
  - output has no questions
  - a question's `audience` is not one of the pool's audiences
  - a select-type question (`single_select`/`multi_select`) has no options
    (unanswerable)
- On success, re-stamp ids as `audience:rN` (guaranteed unique) and return
  the rebuilt list. `_generate_questions` then rebuilds the `ProfileMeta`
  tab list from the surviving audiences exactly as today.

### 4. Gate unchanged
`_generate_questions` still runs the reconciler only when the pool spans
**>1 audience and >1 question**. Folding only matters across profiles, and
running the extra agent on every single-profile round would fight the
token-cost guardrail; within-one-profile simplicity stays the generator
persona's job.

## Tests
- `test_workflow_text.py`: drop the three `extract_kept_ids` tests and the
  import.
- `test_workflow_service.py`:
  - fold-to-one: two profiles ask the overlapping accounts question; the
    reconciler emits a **single, simplified** requester-owned question →
    envelope has exactly one question, its simplified prompt, under
    `requester`, and only that profile tab.
  - malformed output → keep the whole pool.
  - unknown-audience output → keep the whole pool (fallback).
  - update the concurrent-interview test's reconciler output to a
    `<QUESTIONS>` block that keeps both distinct questions.

## Verification
- `cd backend && uv run pytest -q` — all green.
- Live: an accounts/auth issue should show the Product and Eng "how are
  accounts created" overlap collapse to **one** simply-phrased question,
  and Product's questions read as the plainest in the set.
