# Feature Specification: Technical Analysis Step & Document Rendering

**Feature Branch**: `019-technical-analysis-step`

**Created**: 2026-09-18

**Status**: Draft

**Input**: User description: "Rename the gap_analysis workflow step to
technical_analysis (clean breaking rename, no legacy aliases) and make the
web UI render its deliverable as a structured document instead of raw JSON."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator configures the technical-analysis step (Priority: P1)

An operator configures Kestrel with per-step backend and model overrides.
The workflow step that performs the technical analysis is identified by the
name `technical_analysis` in configuration, API responses, and logs. The old
name `gap_analysis` no longer exists anywhere in the system. An operator who
keeps an old config file with a `gap_analysis` key gets a clear startup error
naming the obsolete key and listing the valid keys — not a silent fallback.

**Why this priority**: This is the core of the rename. Every other change
(API, UI, persistence) hangs off the single step identifier, so it must be
right and unambiguous first.

**Independent Test**: Start Kestrel with a config containing
`[step_backends] gap_analysis = "..."` and observe a startup failure that
names `gap_analysis` as obsolete and lists the valid keys. Then start with
`technical_analysis` and observe normal operation; inspect an API workflow
response and confirm the step is named `technical_analysis`.

**Acceptance Scenarios**:

1. **Given** a config file containing a `step_backends.gap_analysis` key,
   **When** Kestrel starts, **Then** startup fails with an error that names
   `gap_analysis` as obsolete and lists the valid step keys.
2. **Given** a config file containing `step_backends.technical_analysis`,
   **When** Kestrel starts, **Then** it boots normally and the override is
   applied to the technical-analysis step.
3. **Given** a workflow in progress, **When** its state is fetched over the
   API (REST or SSE), **Then** the step appears as `technical_analysis` and
   no response anywhere contains the string `gap_analysis`.
4. **Given** an existing database from before the rename, **When** Kestrel
   starts after upgrading, **Then** persisted step rows are rewritten to
   `technical_analysis` and in-progress workflows continue normally.

---

### User Story 2 - The UI renders the analysis as a document (Priority: P1)

A user opens a workflow in the web UI whose technical-analysis step has
completed. Instead of a wall of raw JSON, they see a properly structured
document: headings, paragraphs, lists, code blocks, and links — rendered from
a controlled JSON structure produced by the backend, not from markdown
parsing on the client.

**Why this priority**: This is the user-visible bug that motivated the work.
The rename alone would leave the UI displaying raw JSON for the renamed step.

**Independent Test**: Complete (or seed) a technical-analysis step with a
candidate containing markdown content, open the workflow in the UI, and verify
the deliverable renders as structured document blocks (headings, paragraphs,
lists, code) rather than literal JSON text or raw markdown HTML.

**Acceptance Scenarios**:

1. **Given** a completed technical-analysis step, **When** the user opens the
   workflow panel, **Then** the deliverable renders as a structured document
   (headings, paragraphs, lists, code blocks) — not literal JSON text.
2. **Given** a technical-analysis candidate whose content includes an
   http/https link, **When** the document renders, **Then** the link is
   clickable; any other link target (e.g. `javascript:`) is shown as plain
   text, never rendered as a live link.
3. **Given** a deliverable payload that is malformed or uses an unknown
   version of the document schema, **When** the UI renders it, **Then** it
   shows a controlled error placeholder — never raw JSON and never markdown-
   parsed HTML.
4. **Given** other workflow steps whose deliverables are diffs or plain
   markdown, **When** the user views them, **Then** they render exactly as
   before (no regression to existing formats).

---

### User Story 3 - Operators see consistent terminology everywhere (Priority: P2)

An operator reads logs, API responses, UI labels, and documentation. The step
is consistently called "technical analysis" / `technical_analysis` in every
place they can observe it. No surface still says "gap analysis".

**Why this priority**: Terminology consistency is important for operator trust
but does not block the core rename or rendering; it is polish on top of P1.

**Independent Test**: Grep the codebase and rendered UI for `gap_analysis`,
`GAP_ANALYSIS`, and "gap analysis" — only allowed remnants are historical
changelog/spec text, not live identifiers, labels, or docs describing current
behavior.

**Acceptance Scenarios**:

1. **Given** a running Kestrel instance, **When** an operator inspects UI
   step labels, API responses, and log lines, **Then** the step is referred
   to as technical analysis / `technical_analysis` only.
2. **Given** the operator-facing documentation (setup guides, architecture
   doc), **When** read after the change, **Then** workflow sequences are
   written with `technical_analysis` and no current-behavior reference to
   `gap_analysis` remains.

---

### Edge Cases

- A database contains rows in multiple tables that store the step name
  (`workflow_step`, round-chip table, feedback `target_step`). All must be
  rewritten consistently; a partial rewrite would break re-entry triage and
  round history.
- A persisted deliverable checkpoint is a JSON candidate string. It is NOT
  rewritten by the migration (its internal key is already `technical_
  analysis`); only its *presentation* changes via the new document adapter.
- A technical-analysis candidate contains markdown that does not map cleanly
  to the closed document schema (e.g. nested lists beyond supported depth,
  tables). The builder degrades gracefully: unsupported constructs become
  plain paragraphs or code blocks rather than failing the step.
- An operator config contains BOTH `gap_analysis` and `technical_analysis`
  keys. Startup still fails on the obsolete key; both are reported if both
  are invalid.
- A workflow is in the technical-analysis step when the upgrade happens. The
  rename must not strand it: after migration the running workflow resumes
  under the new name.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST rename the workflow step identifier from
  `gap_analysis` to `technical_analysis` in the backend step enum and all
  internal references (policy defaults, prompt constants, driver module,
  scope/model helpers, markers, profiles).
- **FR-002**: System MUST provide an Alembic migration that rewrites persisted
  `gap_analysis` values to `technical_analysis` in every table that stores the
  step name, and is idempotent (safe to run when no rows match).
- **FR-003**: System MUST reject config files containing obsolete
  `gap_analysis` step keys at startup with an error that names the obsolete
  key and lists the currently valid step keys; no legacy alias or silent
  fallback is permitted.
- **FR-004**: System MUST rename all operator-facing config keys
  (`step_backends`, model overrides) from `gap_analysis` to
  `technical_analysis` (including the `.scope` variant) and update
  `config.toml.example`.
- **FR-005**: Backend MUST serialize the technical-analysis deliverable as a
  versioned, closed JSON document structure (headings, paragraphs, inline
  text/strong/emphasis/code/links, code blocks, ordered/unordered lists,
  rules) produced from the canonical Document model — not raw markdown and
  not the internal candidate JSON.
- **FR-006**: API MUST return the technical-analysis deliverable under an
  explicit document format (a new `deliverable_format` value) carrying the
  structured JSON, so the UI can distinguish it from markdown and diff
  formats.
- **FR-007**: Frontend MUST render the structured document through Vue
  interpolation of a typed schema — never raw HTML injection; links are
  restricted to safe protocols (http/https) matching the existing markdown
  renderer's policy, with unsupported link targets rendered as plain text.
- **FR-008**: Frontend MUST treat malformed or unknown-version document
  payloads as a controlled display failure (error placeholder), never falling
  back to markdown parsing or raw JSON display.
- **FR-009**: System MUST update the frontend step type contract, step label
  maps, and all test fixtures that reference `gap_analysis` to use
  `technical_analysis`.
- **FR-010**: System MUST update operator-facing documentation (architecture
  doc, setup guides) so workflow sequences read `technical_analysis` and no
  current-behavior description references `gap_analysis`.
- **FR-011**: Existing LLM protocol tags (`<TECH_ANALYSIS>`), the candidate
  JSON key `technical_analysis`, the task sentinel, and the committed
  artifact filename `technical-analysis.md` MUST remain unchanged.
- **FR-012**: The internal JSON candidate remains the durable checkpoint format
  for operational state (revision, approval, publication, recovery); only its
  presentation changes.

### Key Entities

- **Workflow Step**: A named stage in the workflow sequence; its identifier is
  persisted, transmitted over the API/SSE, and referenced by operator config.
  The rename changes this identifier from `gap_analysis` to
  `technical_analysis`.
- **Deliverable Document**: The structured output of a completed step as shown
  to the user. For technical analysis it is now a versioned closed JSON
  document derived from the canonical Document model, distinct from the
  internal candidate checkpoint string.
- **Step Config Key**: An operator-facing configuration entry selecting the
  backend/model for a step; renamed in lockstep with the step identifier.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero occurrences of `gap_analysis` / `GAP_ANALYSIS` as live
  identifiers, config keys, API values, UI labels, or current-behavior doc
  text (historical changelog/spec entries excepted).
- **SC-002**: Starting Kestrel with a pre-rename config fails fast with an
  error naming the obsolete key and listing valid keys; starting with a
  post-rename config succeeds.
- **SC-003**: Upgrading a pre-rename database leaves no `gap_analysis` rows in
  any step-name column, and an in-progress technical-analysis workflow resumes
  correctly after upgrade.
- **SC-004**: The technical-analysis deliverable renders in the UI as
  structured document blocks (verified by a frontend test asserting block
  types rather than literal JSON text), with http/https links clickable and
  non-http link targets shown as text.
- **SC-005**: Existing diff and markdown deliverables render identically to
  before (no regression in their tests).

## Assumptions

- The rename is a clean break: this is a personal single-user tool, so no
  backward-compatible alias or deprecation window is required.
- The canonical Document model and its existing renderers (markdown, text,
  ADF) are stable; only a new JSON renderer/adapter is added for the web UI.
- The frontend already has a markdown-it-based renderer with an html:false,
  link-policy we can mirror for the document renderer's safe-link rule.
- Alembic is the migration path and existing deployments run `alembic upgrade`
  on start or via operator action.
- Test fixtures that hard-code six-step sequences must be updated to the new
  name; no fixture should continue to assert the old identifier.
