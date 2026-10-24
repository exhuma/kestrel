# Implementation Plan: Canonical Document Artifacts

## Technical Context

- Backend: Python/FastAPI with source adapters behind `TaskSource`.
- Canonical model: immutable block-and-inline document values.
- Outputs: Markdown strings for Markdown-native sources and Jira Server/DC;
  ADF values for Jira Cloud.
- Compatibility: existing stored text remains readable through an explicit
  legacy-text block during migration.

## Constitution Check

- The document model remains backend-owned and pure.
- No new dependency is needed; the supported document vocabulary is small.
- Renderer behavior is contract-tested before adapter wiring changes.
- Existing task source and persisted workflow history remain usable.

## Design

1. Add `app.services.documents` with immutable document values, builders, and
   pure Markdown, plain-text, and ADF renderers.
2. Replace the Jira outbound Markdown parser with direct ADF rendering from the
   document model. Keep ADF inbound normalization separate.
3. Extend source comment boundaries to accept canonical documents while
   accepting strings temporarily for historic call sites.
4. Convert deterministic review and lifecycle posts to explicit documents.
5. Convert agent artifacts incrementally through an explicit legacy-text block;
   later prompt-contract changes can replace that block with parsed structured
   content without changing renderers or adapters.

## Validation

1. Unit-test canonical documents against Markdown, plain text, and ADF output.
2. Verify Jira Cloud receives ADF directly, without outbound Markdown parsing.
3. Verify Markdown-native and Server/DC sources retain equivalent content.
4. Run the backend test suite and `task quality`.
