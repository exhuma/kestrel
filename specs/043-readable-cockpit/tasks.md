# Tasks: A readable cockpit (043)

- [X] T001 Feed: `lib/eventPayload.ts` `parsePayload`; `FeedEntry.vue` shows detail as a sentence and other fields as labelled values, never `{}` or JSON (FR-001, FR-002).
- [X] T002 Markdown: restore `markdown-it` and `lib/markdown.ts` (html off, safe links open in a new tab); `common/ArtifactText.vue` (JSON stays preformatted); artifact content reports `mime_type` (FR-003).
- [X] T003 Use Markdown in the artifact dialog (by media type, and for the original request), the inline restatement, the card detail, and interview prompts (FR-004, FR-005).
- [X] T004 Rail: gate slots open `gate.target_artifact` first; the dialog shows the gate decision (FR-006, FR-007).
- [X] T005 PR link: migration adds `board_workflow.change_request_url`; delivery records it; the snapshot exposes it; the rail's Pull request entry is a link (FR-008, FR-009).
- [X] T006 Screenshots: coder and verifier prompts; `CodeHost.file_url`; the workspace lists `.kestrel/screenshots/`; `delivery_body.pr_body`; the body is written at open only; remove `screenshots_root` (FR-010 to FR-014).
- [X] T007 Tests, docs and docstrings (FR-015 wording), full gate, UI screenshots, commit, push.
