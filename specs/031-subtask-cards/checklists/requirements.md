# Specification Quality Checklist: Sub-tasks as cards inside the parent workflow

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-29
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

- The four load-bearing design questions were settled with the developer
  before this spec was written (2026-09-29; recorded in the spec's *Context*
  and on Vikunja task 708), so no clarification markers were needed.
- The spec deliberately names existing kestrel concepts (cards, gates, CAB-2,
  the cockpit, the stage board) and removed internals (FR-016–FR-018,
  SC-006). This is a reversal of shipped behaviour, and the deletion scope is
  part of the requirement, not an implementation choice. It follows the
  convention of specs 029 and 030.
- The spec does not settle two assumptions, left to `/speckit.plan`: whether
  verification cards are created deterministically, and how remediation work
  is linked back to its task.
