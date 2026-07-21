# Specification Quality Checklist: Jira Ingestion & Autonomous Design/Code/Verify Loop

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-07-21
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

- Load-bearing scope decisions resolved with the requester (recorded in the spec's
  Clarifications, Session 2026-07-21): configurable repository-resolution field;
  reshape the existing workflow into **one unified, source-agnostic** workflow rather
  than fork it (GitHub-sourced runs deliberately adopt the PRD gate + autonomous
  design/code/verify — the task source is only the human↔agent boundary); bounded
  verify iterations with escalation to Jira; poll-only transport with a webhook-ready
  seam; **thin** task-source notifications (deep-link only) with clarification/approval
  handled in kestrel's existing questionnaire/approval UI. No open [NEEDS CLARIFICATION]
  markers remain.
- Predictability constraint (US4, FR-024–FR-026): there is **no source-conditional
  gating**; every run traverses the same phases and gates. This changes existing GitHub
  behavior on purpose — the plan must account for migrating the GitHub/manual paths onto
  the unified workflow, not merely leaving them intact.
- Two constitutional touch-points to reconcile during `/speckit-plan`: (1) schema
  changes for Jira attribution / repo-resolution / dismissal / verify-iteration
  tracking MUST go through Alembic migrations (Principle II); (2) unlike the GitHub
  webhook, this feature adds **no** off-loopback endpoint, so it introduces no new
  access-model exception — the plan should confirm this and note that a future Jira
  webhook would require a MINOR amendment.
- Constitution IV: the Task Source / Code Host extraction (FR-022–FR-026) is the
  deliberately-deferred abstraction from feature 002, now justified by a second
  concrete source; the plan should treat it as an extraction, not new framework.
- Folded in after the positioning discussion (Clarifications, Session 2026-07-21):
  (1) **Self-hostable code host is first-class** (FR-023a) — the Jira-resolved repo may
  live on a self-hosted GitLab/Gitea, reflecting kestrel's sovereignty posture; the plan
  ships GitHub + a GitLab reference `CodeHost` (two concrete impls justify the port).
  (2) **Behavioural, evidence-grounded verification** (FR-015a, FR-015b, SC-006a) — the design
  **assumes** the verifier runs the modified project and exercises its real boundary (real HTTP
  requests for HTTP APIs like FastAPI; Playwright drive/visual inspection for web GUIs like Vite
  apps — the two initial boundaries). The **exact behavioural harness is out of scope for this
  feature** (delivered incrementally; Playwright not added now); v1 ships the generic
  `Observation{kind}`/`Evidence` interface + a minimal `check` gatherer, so the harness drops in
  later with no workflow reshape.
- Deferred (explicitly out of scope): ingesting free-text Jira comment replies or
  Jira status transitions as clarification answers / PRD decisions; multi-repository
  RFCs; a shipped Jira webhook endpoint; code hosts beyond GitHub + one self-hosted git
  host (GitLab reference); the behavioural verification harness (app launch + HTTP/Playwright
  exercise + boundary detection — assumed by the design, delivered incrementally); richer
  executable acceptance criteria from refinement/design (the verify-grounding future-iteration
  area).
