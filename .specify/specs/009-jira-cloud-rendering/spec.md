# Feature Specification: Jira Cloud Review Rendering

**Feature Branch**: `[009-jira-cloud-rendering]`

**Created**: 2026-09-14

**Status**: Draft

**Input**: User description: "Render source-neutral Kestrel comments as
Atlassian Document Format for Jira Cloud while preserving plain-text Jira
Server/DC and GitHub/local comments."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Review a Jira Cloud gate (Priority: P1)

As an RFC reviewer, I want a Kestrel review comment on Jira Cloud to render
with readable headings, lists, and response commands, so I can understand and
act on the review without malformed Markdown.

**Why this priority**: A readable, copyable gate is necessary for Jira-based
workflow approvals to work.

**Independent Test**: Post a review, then verify Jira Cloud receives a valid
document body with the artifact, review token, and distinct response commands.

**Acceptance Scenarios**:

1. **Given** an active Jira Cloud source, **When** Kestrel posts a review
   gate, **Then** Jira receives an ADF document that renders headings,
   paragraphs, and lists correctly.
2. **Given** a reviewer reads the gate, **When** they choose a decision,
   **Then** the approve, reject, and request-changes commands are individually
   copyable and include the active review token.

---

### User Story 2 - Use Jira Server/DC unchanged (Priority: P2)

As an operator of Jira Server/DC, I want existing plain-text comment behavior
to remain available, so upgrading Kestrel does not require an ADF migration.

**Why this priority**: Jira deployments have incompatible REST body formats.

**Independent Test**: Post a comment through a Server/DC source and verify the
v2 endpoint receives the original string body.

**Acceptance Scenarios**:

1. **Given** a Jira Server/DC source, **When** Kestrel posts any comment,
   **Then** the v2 endpoint receives the unchanged text body.

### Edge Cases

- Jira Cloud descriptions and feedback comments can arrive as ADF; Kestrel
  preserves readable text and review tokens when ingesting them.
- Unsupported Markdown remains readable text rather than producing invalid
  ADF or a nested list.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Kestrel MUST retain one source-neutral canonical comment input.
- **FR-002**: Jira Cloud MUST receive every posted Kestrel comment as valid
  Atlassian Document Format through the v3 REST API.
- **FR-003**: GitHub and local sources MUST keep their existing Markdown
  comment output.
- **FR-004**: Jira Server/DC MUST keep its v2 string-body comment behavior.
- **FR-005**: Jira Cloud configuration MUST explicitly declare a Cloud
  deployment.
- **FR-006**: Jira Cloud ADF descriptions and comments MUST be normalized to
  readable text before Kestrel uses them as task or feedback input.
- **FR-007**: Review gates MUST list distinct copyable commands for approval,
  rejection, and requested changes, each with the review token.

### Key Entities

- **Canonical comment input**: Source-neutral controlled Markdown emitted by
  Kestrel workflow logic.
- **Jira document renderer**: Adapter-owned conversion between canonical
  Markdown and Jira Cloud ADF.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of Jira Cloud comment payloads use valid ADF documents.
- **SC-002**: Each review decision can be copied from one distinct command
  line without manually adding a review token.
- **SC-003**: Existing Jira Server/DC comment payloads remain string bodies.

## Assumptions

- The configured `atlassian.net` source is Jira Cloud.
- The controlled Markdown subset covers headings, paragraphs, rules, ordered
  and unordered lists, bold text, and inline code.
