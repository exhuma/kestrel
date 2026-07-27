# Feature Specification: Behavioral Verify Evidence

**Feature Branch**: `feat/005-behavioral-verify-step`

**Created**: 2026-07-24

**Status**: Draft

**Input**: User description: "Ground the verify step's adjudication in observed
behavior of the running, modified project, not just a diff read and check exit
codes. Delegate live exercising of the app (real HTTP requests for an API
boundary, browser-driven interaction for a UI boundary) to the verifying
agent's own tools rather than kestrel building a dedicated harness. Infer the
project's boundary type during design, not via kestrel-side detection. Split
verify's adjudication into a hard requirement-conformance gate (weighed on
behavioral + deterministic evidence) and advisory code-quality/documentation
feedback that never blocks acceptance on its own. Record what verify observed
as a committed audit-trail artifact, not a re-run regression contract.
Strengthen the coder's instructions to practice TDD so durable test coverage
stays the coder's responsibility."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Verify grounds acceptance in real, observed behavior (Priority: P1)

Today, when a run's `verify` step accepts an implementation, that acceptance
means "the diff looked consistent with the PRD/design and the configured
checks passed" — it never confirms the modified project actually *works* the
way the PRD describes when it's running. An operator reviewing an accepted
run for a project with an HTTP API or a web UI should be able to trust that
the implementation was actually launched and exercised — not just read as
text — before being accepted.

**Why this priority**: This is the core gap the feature closes. Every other
change (boundary classification, the hard/soft adjudication split, the audit
trail) exists to support this one outcome: acceptance reflecting real,
observed behavior rather than a plausible-looking diff.

**Independent Test**: Run a project with a classified HTTP or UI boundary
through refine → design → code → verify. Confirm the verify round records at
least one observation describing a real interaction with the running
application (a request/response pair, or a browser interaction/visual
inspection) — not merely diff/PRD text comparison — before the run reaches
`done`.

**Acceptance Scenarios**:

1. **Given** a project whose boundary is classified as an HTTP API, **When**
   the verify step runs, **Then** the verify round's recorded evidence
   includes at least one observation describing a real HTTP request made
   against the running, modified application.
2. **Given** a project whose boundary is classified as a web UI, **When** the
   verify step runs, **Then** the verify round's recorded evidence includes at
   least one observation describing a real browser-driven interaction with
   the running, modified application.
3. **Given** the implementation does not actually behave as the PRD describes
   when exercised live (even though the diff looks plausible), **When** the
   verify step runs, **Then** the round is rejected with feedback describing
   the specific observed failure.

---

### User Story 2 - Requirement conformance gates acceptance; code quality only advises (Priority: P2)

An operator wants verify to reject work that doesn't do what the PRD asked
for, but not to get stuck in an endless reject/retry loop over stylistic or
maintainability nitpicks. Verify's job is to check the result the way an
end-user/stakeholder would judge it; code-quality and documentation
observations are still valuable, but as feedback, not as a blocker.

**Why this priority**: This resolves a real, previously-unresolved tension in
how verify should judge results, and directly bounds the risk introduced by
User Story 1 (a stricter, behavior-grounded verifier could otherwise reject
far more often, including for reasons unrelated to whether the feature
works).

**Independent Test**: Produce an implementation that behaviorally satisfies
the PRD (passes all checks and behavioral observations) but has an identified
code-quality or documentation shortcoming. Confirm the round is still
accepted, and the shortcoming appears in the verifier's feedback text.

**Acceptance Scenarios**:

1. **Given** all configured checks and behavioral observations pass, **When**
   the verifier also notes a code-quality or documentation concern, **Then**
   the round is still accepted and the concern appears in feedback.
2. **Given** any configured check or behavioral observation fails, **When**
   the verifier evaluates the round, **Then** the round is rejected regardless
   of what the verifier's own narrative says about the implementation's
   quality.

---

### User Story 3 - What verify observed is recorded, without becoming a stale contract (Priority: P3)

An operator reviewing a completed (or escalated) run wants to see what the
verifier actually checked and found, as part of the run's history — without
that record turning into a regression suite that a later, unrelated run gets
blocked by when the product has naturally moved on.

**Why this priority**: Lower priority than getting the verdict right (US1,
US2), but necessary for the feature to be trustworthy and inspectable over
time, and to avoid a known failure mode (self-graded, drifting test debt)
called out during design.

**Independent Test**: Complete a run and confirm a human-readable record of
that run's verify findings exists alongside the run's other handover
artifacts (PRD, design). Start a second, unrelated run against the same
repository and confirm its verify step is not required to satisfy anything
recorded by the first run's artifact.

**Acceptance Scenarios**:

1. **Given** a run's verify step has completed at least one round, **When**
   the run finishes (accepted or escalated), **Then** a human-readable record
   of what was checked and observed is committed alongside the run's other
   handover artifacts.
2. **Given** a prior run's committed verify record describes behavior that a
   later run's change intentionally alters, **When** the later run's verify
   step evaluates its own implementation, **Then** it is judged solely against
   the current PRD/design/live behavior — the prior record is not re-checked
   or treated as a requirement.

---

### Edge Cases

- What happens when the design step cannot confidently classify a project's
  boundary (e.g., a library or CLI tool with no HTTP/UI surface)? Verify falls
  back to today's behavior: configured checks plus diff/PRD judgment, with no
  behavioral exploration expected or required.
- What happens when the classified boundary is HTTP or UI, but the operator's
  environment doesn't actually have the tooling needed to exercise it (e.g.,
  no browser-automation tool available for a UI boundary)? The round's
  feedback must say verification was degraded or incomplete for that reason —
  it must not read the same as an ordinary, fully-verified pass.
- What happens when the implementation genuinely satisfies the PRD but the
  live application fails to start at all (e.g., a startup crash)? This is
  itself a real behavioral failure and must reject with the specific
  observed failure (the process didn't come up), not be silently skipped.
- What happens when a project exposes both an HTTP API and a web UI? Both
  kinds of live exercise are expected; a failure observed in either is
  sufficient to reject the round.
- What happens if something the verifier launches while exploring (e.g., a
  dev server) is still running when exploration ends? It is the verifying
  agent's responsibility to stop what it started; kestrel does not add new
  process-lifecycle management to compensate.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The design step MUST classify the project's user-facing
  boundary — HTTP API, web UI, both, or none — once per run, and that
  classification MUST remain available to the verify step for every
  subsequent verify round of that run.
- **FR-002**: When the classified boundary is HTTP, UI, or both, the verify
  step MUST attempt to launch the modified project and exercise it for real
  — real HTTP requests for an HTTP boundary, real browser-driven interaction
  for a UI boundary — before rendering a verdict, using whatever tooling is
  already available to the verifying agent.
- **FR-003**: When the classified boundary is "none," the verify step's
  behavior is unchanged from today (configured checks plus diff/PRD
  judgment; no behavioral exploration is expected).
- **FR-004**: The verify step MUST continue to run every operator-configured
  check exactly as it does today, independent of and in addition to any
  behavioral exploration.
- **FR-005**: A failing observation — whether from a configured check or from
  the verifier's own behavioral exploration — MUST force the verify round to
  reject, regardless of what the verifier's own narrative or verdict text
  says (the failing-observation invariant, extended to cover behavioral
  evidence).
- **FR-006**: The verify step's accept/reject decision MUST be driven by
  requirement/design conformance, evidenced by configured checks and
  behavioral observations. Code-quality, maintainability, and documentation
  observations MUST be surfaced as feedback but MUST NOT, on their own, force
  a rejection.
- **FR-007**: When the operator's environment lacks the tooling needed to
  exercise a classified boundary, the verify round's feedback MUST explicitly
  state that verification was degraded or incomplete, rather than being
  indistinguishable from an ordinary pass.
- **FR-008**: Each completed run MUST produce a human-readable record of what
  its verify round(s) checked and observed, committed to the repository
  alongside the run's other handover artifacts (PRD, design).
- **FR-009**: A run's committed verify record MUST NOT be treated as a
  requirement any other run's verify step is obligated to satisfy or
  reproduce.
- **FR-010**: The coder step's instructions MUST require the implementation
  to include its own automated tests (following test-first practice and a
  reasonable mix of unit/integration coverage) as part of considering the
  work done.
- **FR-011**: The verify step's final accept/reject decision MUST continue to
  be produced in a reliably machine-parseable form, at least as reliably as
  the current mechanism.

### Key Entities

- **Boundary Classification**: The project's user-facing surface type (HTTP
  API, web UI, both, or none), determined once per run during design and
  reused by every verify round of that run.
- **Verify Round**: One pass of the verify step; produces a set of
  observations and an accept/reject decision with feedback.
- **Observation**: One measured or self-reported outcome within a verify
  round — a configured check's result, a real HTTP interaction, or a real UI
  interaction — each with a pass/fail outcome and a bounded description.
- **Verify Record (audit artifact)**: The committed, human-readable summary
  of a verify round's observations and decision, kept as run history rather
  than as a contract for future runs.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For any run against a project with an HTTP or UI boundary, an
  operator reviewing an accepted run can find at least one recorded
  observation describing a real interaction with the running application —
  not merely a description of how the diff compares to the PRD.
- **SC-002**: Verify rejections caused by an observed behavioral failure
  include specific, actionable detail sufficient for the next coding attempt
  to address the failure without the operator having to reproduce it
  manually.
- **SC-003**: 100% of verify rounds where boundary-appropriate tooling was
  unavailable say so explicitly in their feedback, rather than reading as an
  ordinary pass.
- **SC-004**: An operator can reconstruct what any completed run's verify
  step checked and found using only the run's committed artifacts, without
  needing access to application logs or the (torn-down) run workspace.
- **SC-005**: No verify round is rejected on the basis of code-quality or
  documentation feedback alone when all configured checks and behavioral
  observations pass.
- **SC-006**: No run's verify step is ever blocked, slowed, or rejected due
  to a different run's previously committed verify record.

## Assumptions

- The operator's configured backend (Claude CLI, opencode, etc.) already has,
  or the operator is responsible for configuring, whatever tools (browser
  automation, HTTP clients) are needed to exercise a given project's
  boundary. Kestrel does not install, manage, or probe for the presence of
  such tooling itself — it delegates live exercising of the app entirely to
  the verifying agent's own capabilities.
- The verify step's exploratory work is bounded by the same per-backend turn
  mechanism already governing every other step; this feature does not
  introduce a new timeout or tool-budget mechanism.
- Cleanup of anything the verifying agent launches while exploring (e.g., a
  dev server) is handled by instructing the agent to stop what it started;
  this feature does not add new process-lifecycle management on kestrel's
  side.
- The committed verify record is not given a new dedicated UI view in this
  feature — it is visible the same way the PRD/design artifacts already are
  (via the repository/PR), and the frontend's existing accept/reject
  indicator is sufficient for v1.
- Projects whose boundary is classified as "none" (e.g., libraries, CLI
  tools) keep today's check-and-diff-judgment verify behavior unchanged.
- Behavioral observations are self-reported by the verifying agent rather
  than independently re-measured by kestrel; this is an accepted trade-off
  in exchange for not building and maintaining a dedicated verification
  harness.
