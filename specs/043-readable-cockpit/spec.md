# Feature Specification: A readable cockpit

**Feature Branch**: `work`

**Created**: 2026-09-30

**Status**: Implemented (2026-09-30)

**Input**: The operator's review of the current cockpit ("minor nits"): the
timeline often shows empty curly braces and shows a detail as a raw object;
Markdown is not rendered; the pull request link and the reviewed documents
(PRD, CAB-1 decision, understanding check) are not reviewable from the
artifact list; PRs for UI work should include screenshots where technically
possible.

## Context

- **The feed prints the raw payload.** Every event carries a JSON payload,
  almost always `{}`. The feed prints it verbatim, so most rows end in a
  literal `{}`. The only non-empty shape the backend emits is
  `{"detail": "…"}`, and it is shown as raw JSON.
- **Markdown is shown as source.** Specialists write Markdown (the
  restatement, the PRD, interview questions) and the request body usually is
  Markdown. Feature 029 FR-015 requires artifact content to be "rendered as
  text, never as markup", so headings, lists and links appear as raw syntax.
- **Gate entries on the rail show the wrong artifact.** The Understanding
  check, CAB-1 decision, Interview rounds and PRD entries read the gate
  card's *own* artifact. That is the operator's response, often absent. The
  document the operator reviewed is the gate's target artifact, which belongs
  to the producing card. So these entries are often unavailable or show only
  the operator's note.
- **The pull request is never reachable.** Delivery opens a change request
  but records only its number. No artifact is written for the delivery card,
  so the "Pull request" entry never opens.
- **Nothing produces screenshots.** kestrel opens the PR itself with a fixed
  body. No specialist is asked to capture screenshots, and a leftover
  `screenshots_root` setting points at code that no longer exists.

## Decisions

- **Markdown, safely.** Content known to be Markdown is rendered as
  formatted Markdown. Raw HTML in the source is escaped, not interpreted.
  Links with unsafe protocols (`javascript:`, `vbscript:`, `data:`) are
  dropped. Nothing in agent output can become live markup. Content that is
  not Markdown (for example a JSON interview artifact) stays preformatted
  text. This amends feature 029 FR-015.
- **The rail opens what was reviewed.** For a gate slot, the rail prefers the
  gate's target artifact and falls back to the gate card's own. The
  Executive summary is the exception: it *is* the CAB-2 gate's own artifact
  (feature 030).
- **The PR is a link, not a document.** The Pull request entry opens the
  change request on the code host in a new tab.
- **Screenshots are the coder's job; the verifier checks them.** Only the
  coder holds a write lease and commits, so the coder captures and commits
  them. The verifier treats their unexplained absence on a UI change as a
  verification gap: internal remediation, not an escalation.
- **The PR body is written once.** Delivery composes it when it opens the
  change request. Later deliveries (CI remediation) push to the same change
  request and do not rewrite its body.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A feed without noise (Priority: P1)

The operator reads a request's timeline and sees only what each event means.
Rows carry no empty payloads, and a failure's reason reads as a sentence.

**Why this priority**: The feed is the page's main surface. `{}` on most rows
is the most visible defect.

**Independent Test**: Load a request whose events include empty payloads and
a `detail` payload. Check that no row shows braces and that the detail reads
as plain text.

**Acceptance Scenarios**:

1. **Given** an event whose payload is `{}`, empty, or unreadable, **When**
   the feed renders it, **Then** the row shows its summary line only.
2. **Given** an event whose payload has a `detail`, **When** the feed renders
   it, **Then** the detail appears as a secondary sentence under the summary,
   with no JSON punctuation.
3. **Given** an event whose payload has other fields, **When** the feed
   renders it, **Then** each field appears as a labelled value.

### User Story 2 - Markdown reads as a document (Priority: P1)

The operator opens the PRD, the restatement or the original request and sees
formatted headings, lists, emphasis, code and links.

**Why this priority**: These documents are what the operator approves.
Reading raw Markdown makes that approval harder.

**Independent Test**: Open a Markdown artifact that contains headings, a
list, a link, a `<script>` tag and a `javascript:` link. Check that the
formatting renders, the tag shows as literal text, and the unsafe link is
not clickable.

**Acceptance Scenarios**:

1. **Given** an artifact stored as Markdown, **When** the operator opens it
   from the rail, **Then** it is rendered as formatted Markdown and its trust
   level is still shown.
2. **Given** an artifact stored as something other than Markdown, **When**
   it is opened, **Then** it is shown as preformatted text, unchanged.
3. **Given** Markdown containing raw HTML or an unsafe link, **When** it is
   rendered, **Then** the HTML shows as literal text and the unsafe link is
   not a link.
4. **Given** the understanding gate, a card's detail, or an interview
   question, **When** its text is Markdown, **Then** it is rendered the same
   way.

### User Story 3 - Every reviewed artifact is reviewable (Priority: P1)

From the artifact rail, the operator opens the understanding restatement,
the strategic-fit answers behind CAB-1, the interview questions and the PRD.
These are the documents each gate reviewed. Once delivery has run, the
operator can follow the Pull request entry to the change request.

**Why this priority**: The rail exists to keep the durable documents at
hand (feature 029 FR-014). Today several of its entries can't be opened.

**Independent Test**: Drive a request past the understanding and PRD gates,
approving without a note, then deliver it. Check that each of those rail
entries opens the reviewed document and shows the decision, and that Pull
request opens the change request URL.

**Acceptance Scenarios**:

1. **Given** an approved understanding gate with no operator note, **When**
   the operator opens "Understanding check", **Then** the restatement opens,
   marked Approved.
2. **Given** a PRD gate, **When** the operator opens "PRD", **Then** the PRD
   draft that gate reviewed opens.
3. **Given** a gate whose target artifact is unknown, **When** the rail is
   built, **Then** the entry falls back to the gate card's own artifact, if
   any.
4. **Given** delivery opened a change request, **When** the operator
   activates "Pull request", **Then** the change request opens in a new tab.
5. **Given** delivery has not run, or ran before this feature, or the code
   host cannot open change requests, **When** the rail is built, **Then**
   "Pull request" is unavailable and is not a link.

### User Story 4 - UI pull requests carry screenshots (Priority: P2)

When the delivered change affects a user interface, the change request shows
screenshots of the changed screens. If no screenshots could be taken, it
says why.

**Why this priority**: Screenshots speed up the operator's review of UI work.
They depend on the specialist's tooling, so this is best-effort.

**Independent Test**: Deliver a workflow whose branch contains committed
screenshots under `.kestrel/screenshots/`, and one whose branch contains only
a README there. Check the opened change request's body in both cases.

**Acceptance Scenarios**:

1. **Given** a coder card whose change affects a UI and a browser tool is
   available, **When** the coder finishes, **Then** PNG screenshots of the
   changed screens are committed under `.kestrel/screenshots/`.
2. **Given** screenshots cannot be taken, **When** the coder finishes,
   **Then** `.kestrel/screenshots/README.md` states why.
3. **Given** a UI change with neither screenshots nor a README, **When** the
   verifier checks it, **Then** it reports a `verification_gap`.
4. **Given** committed screenshots, **When** delivery opens the change
   request, **Then** its body has a "Screenshots" section that shows each one
   as an image from the pushed branch.
5. **Given** only a README, **When** delivery opens the change request,
   **Then** the Screenshots section states its reason.
6. **Given** neither, **When** delivery opens the change request, **Then**
   the body has no Screenshots section.

### Edge Cases

- A payload that is valid JSON but not an object (for example `"x"` or `[]`)
  is treated as having nothing to show.
- A `detail` that is not a string is shown as a labelled value.
- An empty Markdown artifact shows as empty, not as an error.
- Markdown links open in a new tab and cannot reach the opener
  (`rel="noopener noreferrer"`).
- A later delivery to an existing change request keeps the stored URL.
- Screenshot file names are used as image alt text. Names are
  URL-path-encoded in the image link.
- A missing `.kestrel/screenshots/` directory is the same as "neither".

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The feed MUST NOT show a payload that is empty, `{}`,
  unreadable, or not an object.
- **FR-002**: The feed MUST show a payload's string `detail` as plain text
  under the event's summary, and any other payload fields as labelled
  values. It MUST never show raw JSON.
- **FR-003**: The artifact content response MUST report the artifact's media
  type.
- **FR-004**: Text content — the original request body and any artifact
  that is not structured data — MUST be rendered as formatted Markdown.
  Artifacts written before this feature are all stored as `text/plain`,
  so structured data is recognised by a JSON media type *or* by content
  that parses as JSON; the PRD and question artifacts now record their
  true media type.
  This applies wherever they are shown: the artifact dialog, the inline
  restatement on the understanding gate, the card detail, and interview
  question prompts.
- **FR-005**: Markdown rendering MUST escape raw HTML and MUST NOT produce
  links with `javascript:`, `vbscript:` or `data:` targets. Structured
  data (JSON) MUST be shown as preformatted text. This amends feature
  029 FR-015. The provenance (trust) requirement of FR-015 is unchanged.
- **FR-006**: The rail's Understanding check, CAB-1 decision and PRD
  entries MUST open the representative gate's target artifact, when it
  has one, and otherwise the card's own artifact. Interview rounds and the
  Executive summary MUST prefer the gate card's own artifact (the
  operator's answers; the rendered summary), falling back to the target.
- **FR-007**: A rail entry backed by a resolved gate MUST show that gate's
  decision (Approved / Rejected) in its dialog.
- **FR-008**: When delivery opens a change request, the system MUST record
  its URL with its number. A later delivery to the same change request MUST
  NOT clear it.
- **FR-009**: The board snapshot MUST expose the recorded change request URL.
  The rail's Pull request entry MUST be a link to it, opening in a new tab,
  when present, and unavailable otherwise.
- **FR-010**: The coder specialist's instructions MUST require screenshots
  (or a README reason) under `.kestrel/screenshots/` for UI-affecting
  changes, committed on its branch.
- **FR-011**: The verifier specialist's instructions MUST classify a
  UI-affecting change with neither as a `verification_gap`.
- **FR-012**: When delivery opens a change request, its body MUST embed each
  committed `.kestrel/screenshots/*.png` as an image. Each image link is the
  code host's URL for that file on the pushed branch. If there are no PNGs
  but a README exists, the body MUST state the README's text instead.
  Otherwise the body has no Screenshots section.
- **FR-013**: Deliveries that update an existing change request MUST NOT
  rewrite its body.
- **FR-014**: The unused `screenshots_root` setting MUST be removed.

### Key Entities

- **Workflow delivery record**: the change request's number (existing) and,
  new, its URL. Both are empty until delivery opens one.
- **Artifact content**: content, trust, and, new, media type.
- **Screenshot set**: the PNG files and optional README under
  `.kestrel/screenshots/` on the workflow's branch at delivery time.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: No feed row for any event emitted today shows `{}` or any JSON
  punctuation.
- **SC-002**: Every rail entry whose gate has a target artifact opens a
  document. For a request past the PRD gate, that is 4 of 4 gate entries,
  up from as few as 0.
- **SC-003**: After delivery opens a change request, the operator reaches it
  from the cockpit in one click.
- **SC-004**: No Markdown input (including `<script>`, event-handler
  attributes, or `javascript:`/`data:` links) produces live markup or an
  executable link.
- **SC-005**: A delivered UI change's change request shows its screenshots,
  or the reason there are none, without opening the branch.

## Assumptions

- The GitHub and GitLab code hosts can each produce a stable URL for a file
  on a branch. Images from a private repository render for viewers who have
  access to it.
- Specialists may have no browser tool. The README reason covers that, which
  makes screenshots best-effort ("where technically possible").
- Changes pushed after the change request was opened (CI remediation) do not
  refresh the Screenshots section. Rewriting PR bodies is out of scope.
- Workflows delivered before this feature have no recorded URL and are not
  backfilled.
- Session transcripts, titles, reasons and option labels stay plain text.
