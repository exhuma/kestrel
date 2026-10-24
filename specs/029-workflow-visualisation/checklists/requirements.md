# Specification Quality Checklist: Workflow visualisation rework

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-28
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

Two decisions that would otherwise have been `[NEEDS CLARIFICATION]` markers
were settled with the developer on 2026-09-28 before the spec was written, and
are recorded in Assumptions rather than left open:

1. **Navigation mechanism** — adopt a routing library rather than extend the
   existing single-parameter deep-link reader. Principle IV justification is
   owed in the plan's Complexity Tracking table, not here.
2. **Mockup tracking** — commit the three mockup images (currently swallowed by
   a blanket image ignore rule) so spec and sub-issue references resolve.

## Round 2: adversarial cross-artifact audit (2026-09-28)

After `/speckit.plan` and `/speckit.tasks`, a full audit was run across spec, plan,
research, data-model, contracts and tasks — checking FR coverage, orphan tasks,
inter-artifact contradictions, verifiability, and **spot-checking ~40 factual claims
against the repository**. It found 32 defects, 9 of them HIGH. All are resolved.

**The one that mattered.** The spec asserted "the backend is complete for this
feature". It was not. Four facts the surfaces must display are exposed by no
response: human title (`task_label` is the raw `task_ref`), the decomposition parent
link, interview round/cap (028 touched services and config only — zero hits for
`round` in `schemas.py`), and cap exhaustion. The parent link is the serious one: its
absence *is* epic #40's headline complaint, so a frontend-only build would have
shipped a board still failing the defect it was built to fix. The developer chose to
add the four as additive read-only fields (FR-040–FR-043, a new
`contracts/board-api-additions.md`, and a new task phase) rather than weaken the
requirements.

Other HIGH defects resolved:

- **No data path in or out of the interview.** Questions are not an API resource —
  they live as text inside an artifact — and no task performed the submit at all, so
  SC-005 was unimplementable. Now FR-045/FR-046 with tasks.
- **Recovered prior art was over the limits.** `lib/questionnaire.ts` is
  grandfathered for `complexity` and the seed test file for
  `max-lines-per-function`. Renaming to `interview*` (research R10) removes the
  *exemption* but not the *violation* — so recovery now explicitly means "port, then
  split".
- **Done column would always be empty.** The listing drops terminal workflows unless
  `include_completed=true`, which nothing passed. Now FR-044.
- **Draft persistence contradicted itself** — component state cannot survive
  unmounting the route it lives on. Now a module-level singleton, and "autosave"
  reworded to an in-memory draft commit.
- **Wrong cross-spec reference**: the no-dragging rule is spec 026 **FR-032**, not
  FR-030 — and 026 FR-030 actually *mandates* a dependency graph view, so FR-033 now
  records that it supersedes it instead of silently contradicting it.

Corrections of fact (each verified in the repo): `card_type` not `kind`; five phases
precede "PRD sign-off", not six; the per-workflow SSE carries snapshots, not events;
`eslint.config.js:62-92` in a 93-line file, and its entry disables `complexity`, not
a size rule; `main.ts:28-46` for the global defaults; the round cap **defaults to 1**,
making FR-027's "degraded" single-round case the common path.

Scope corrections: `SessionsView` and `NotFoundView` were built by tasks but named in
no inventory and asked for by no requirement — now FR-047 and FR-030 with inventory
entries. `RoundChips.vue` was listed as prior art to recover but nothing recovered it
— now explicitly *not* recovered, with the reason.

## Round 1: resolved during initial validation

- **Round 1 finding — named dependencies leaked into requirements.** An earlier
  draft named the routing library and the graph library in FR-028/FR-033. Both
  were rewritten to state the capability ("its own address", "the third-party
  graph-rendering dependency"); the named choices now live only in Assumptions
  and are the plan's business.
- **Round 1 finding — SC-012 was a count, not an outcome.** Reworded from a bare
  dependency count to the operator-meaningful form: one dependency removed, one
  added and justified against its alternative.
- **Deliberate retention**: FR-006/FR-007/FR-039 cite spec 026 FR-032/FR-031/
  FR-037, and several items cite commit hashes and the rejected-layout mockup.
  These are inherited-constraint and evidence citations, not implementation
  detail — they tell the implementer *why* a requirement is binding and stop it
  being relitigated.
- **Known tension**: FR-036–FR-038 are presentation constraints inherited
  verbatim from epic #40, and are closer to "how" than the rest of the spec.
  Kept because they are binding on every sub-issue and constitution Principle V
  makes the colour rule non-negotiable; the component-by-component mapping stays
  in the plan.
