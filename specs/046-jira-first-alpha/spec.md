# Feature Specification: Jira is where people work with kestrel

**Feature Branch**: `work`

**Created**: 2026-10-05

**Status**: Draft

**Input**: "To make kestrel usable internally and expose it to real users for
a controlled alpha test, we need bidirectional information flow. Users must
only interact with Jira." Refined in conversation (2026-10-02 to 2026-10-05):
interviews keep kestrel's own forms, reached by a link; the kestrel UI stays
available to alpha users as a fallback; Jira is Cloud.

## Context

Kestrel already writes a few one-line comments to the ticket after the fact
("Gate approved: …", "Delivered: …"), but everything a person must read or
decide — the restatement, the PRD, the CAB summaries — exists only in the
kestrel UI, and nothing a person writes on the ticket reaches kestrel. Jira
Cloud only renders its own document format, and kestrel's comment path does
not respect that consistently.

This feature delivers #65 (resolve gates from the task source) under epic
#63, plus the outbound half it needs. It is bound by constitution 1.6.0:
Principle VI (documents are modelled, never strings) and the access model's
fourth constraint (kestrel never changes the status of an ingested task).

### Who is who on a Jira issue

| Person | What they do | Mentioned |
| --- | --- | --- |
| **Reporter** | Confirms the understanding, answers the strategic interview, signs off the PRD | Only on a gate they must answer |
| **Change owner** (a user field on the issue) | Relays the CAB-1 and CAB-2 decisions after the weekly CAB review | When the issue is ready for CAB, and whenever it should change status |
| **CAB members** | Decide in their weekly review, outside kestrel | **Never** |
| **Operator** | Everything in the kestrel UI, as today | Never |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Everything kestrel posts reads properly in Jira (Priority: P1)

A restatement, a PRD with headings, lists and a table, or a CAB-2 summary
arrives on the ticket formatted the way Jira shows its own content, with the
people it is meant for mentioned as real Jira mentions. What people write on
the ticket reaches kestrel with its structure intact.

**Why this priority**: every other story posts or reads comments. A comment
that shows raw markup, or a mention that does not notify, makes the ticket
unusable as the main channel.

**Independent Test**: Post a comment containing every construct kestrel uses
(heading, emphasis, code, link, lists, table, rule, mention) to a Jira Cloud
issue and confirm it renders natively; read a structured comment back and
confirm its structure survives.

**Acceptance Scenarios**:

1. **Given** any comment kestrel posts, **When** it appears on a Jira Cloud
   issue, **Then** it is rendered in Jira's native format: no raw Markdown
   or markup characters are visible.
2. **Given** a comment that mentions a person, **Then** the mention is a
   native Jira mention of that person's account and notifies them.
3. **Given** a ticket body or comment with headings, lists or links,
   **When** kestrel reads it, **Then** it keeps that structure for every
   later use (screening, prompts, display).
4. **Given** kestrel's own marker on its comments, **Then** it is part of
   the comment, never appended as text after rendering.

---

### User Story 2 - The ticket says what is needed, from whom (Priority: P1)

When a gate opens, the ticket gets one comment saying what is needed, from
whom, and how to answer, with the content to decide on and a link to the
kestrel page as fallback. The change owner is told when the issue is ready
for CAB and whenever it should move on; kestrel never moves it.

**Why this priority**: without it nobody outside kestrel knows a decision is
waiting. Alone, it already makes the alpha workable: people read on the
ticket and answer in the kestrel UI.

**Independent Test**: Drive a request through every gate; check that each
opening produces exactly one comment with the right content and mentions,
that the issue's status never changes, and that no CAB member is mentioned.

**Acceptance Scenarios**:

1. **Given** the understanding gate opens, **Then** the ticket shows the
   restatement in full and mentions the reporter, asking them to confirm or
   correct it.
2. **Given** the strategic interview or an interview round opens, **Then**
   the ticket says who is asking and how many questions, links to the
   interview form, and mentions the reporter.
3. **Given** the PRD gate opens, **Then** the ticket shows the PRD in full
   and mentions the reporter.
4. **Given** CAB-1 or CAB-2 opens, **Then** the ticket shows a "ready for
   CAB" summary — the strategic-fit answers, or the executive summary with
   totals, risks and the task table — and mentions the change owner and
   nobody else.
5. **Given** the request is delivered, fails or is cancelled, **Then** the
   ticket tells the change owner it should move on (with the change-request
   link when delivered) and the issue's status is unchanged.
6. **Given** CI on the change request fails, is repaired, or a request is
   escalated, **Then** the ticket gets a plain status comment that mentions
   nobody.
7. **Given** posting a comment fails (Jira unreachable), **Then** kestrel
   retries it later and it is posted exactly once.
8. **Given** the issue has no change owner set, **Then** the "ready for
   CAB" comment says so, and the CAB decision is taken in the kestrel UI.

---

### User Story 3 - A reply on the ticket decides (Priority: P2)

The reporter replies "@kestrel looks right" under the restatement, or
"@kestrel no — it must also cover exports" under the PRD. The change owner
writes "@kestrel CAB approved" after the weekly review. Kestrel acts on it
and confirms on the ticket.

**Why this priority**: it makes Jira the main channel instead of a notice
board; Story 2 already makes the alpha usable without it.

**Independent Test**: With a gate open, post an @kestrel reply as the
entitled person and confirm the gate is resolved exactly as the same answer
in the UI would; post the same reply as someone else and confirm nothing
happens except a short explanation.

**Acceptance Scenarios**:

1. **Given** an open requester gate, **When** the reporter writes an
   @kestrel reply approving it, **Then** the gate is approved and kestrel
   confirms on the ticket.
2. **Given** an open requester gate, **When** the reporter rejects it with a
   reason, **Then** the gate is rejected and the reason is used exactly as a
   correction or feedback given in the UI would be.
3. **Given** a rejection without a reason where one is needed, or a reply
   whose meaning is unclear, **Then** kestrel asks back on the ticket and
   leaves the gate open.
4. **Given** an open CAB gate, **When** the change owner relays the CAB
   decision, **Then** the gate is resolved accordingly.
5. **Given** a reply from anyone not entitled to the open gate, **Then**
   nothing is decided and kestrel replies briefly why.
6. **Given** a reply without an @kestrel mention, or one written by kestrel
   itself, **Then** it is ignored.
7. **Given** a reply the input screening holds back, **Then** nothing is
   decided, the ticket says the reply is held for review, and the operator
   can release it in the UI, after which it is acted on.
8. **Given** a reply arriving after the gate was decided (in the UI or by an
   earlier reply), **Then** nothing changes and kestrel says it was already
   decided, and by whom.
9. **Given** any decision taken from the ticket, **Then** the request's
   history records who decided, and that it came from the ticket.

### Edge Cases

- A reply is edited after kestrel acted on it: the original version stands;
  the edit is ignored.
- Several @kestrel replies arrive before kestrel reads them: they are taken
  in order; the first one that decides wins, the rest get "already decided".
- Kestrel restarts: no comment is posted twice and no reply is acted on
  twice.
- The reporter is also the change owner: they may act on both kinds of gate.
- A requester gate opens while the reporter's account cannot be resolved:
  the comment still posts, without the mention.
- Interview answers are not accepted from the ticket; a reply that tries
  gets a pointer to the interview form.

## Requirements *(mandatory)*

### Faithful documents (Story 1)

- **FR-001**: Everything kestrel posts to or reads from a task source or
  code host MUST be handled internally as a structured document and
  converted only by that system's adapter (constitution Principle VI).
- **FR-002**: Comments posted to Jira Cloud MUST be in Jira's native
  document format, rendered directly from the structured document.
- **FR-003**: A structured document MUST be able to mention a person by
  their account on the target system; Jira renders it as a native mention.
- **FR-004**: Content read from Jira (ticket bodies, comments) MUST be
  converted into a structured document, keeping its structure.
- **FR-005**: Kestrel's ownership marker MUST be part of the structured
  document it posts.
- **FR-006**: The existing violations named by Principle VI MUST be removed,
  and a mechanical check MUST keep parsing and rendering inside adapters.

### Announcements (Story 2)

- **FR-007**: When a requester or CAB gate opens, kestrel MUST post one
  comment per gate opening with the content to decide on, the people asked
  (per *Who is who*), how to answer, and a link to the kestrel page.
- **FR-008**: An interview gate's comment MUST link to its interview form
  and MUST NOT ask for answers on the ticket.
- **FR-009**: The change owner MUST be read from a configured user field on
  the issue. CAB members MUST never be mentioned.
- **FR-010**: Kestrel MUST tell the change owner when the issue should move
  on (ready for CAB; delivered, failed, cancelled) and MUST NOT change the
  ingested issue's status (constitution, fourth access-model constraint).
- **FR-011**: CI results and escalations MUST be reported in plain comments
  without mentions.
- **FR-012**: A comment that failed to post MUST be retried until posted,
  and MUST be posted at most once, across restarts.

### Replies (Story 3)

- **FR-013**: Kestrel MUST read new comments on the tickets of active
  requests, and act on each at most once, across restarts.
- **FR-014**: Only comments containing the plain-text marker `@kestrel`
  MUST be considered. Kestrel's own comments, recognised by the ownership
  marker every kestrel comment carries (FR-005), MUST be skipped, even
  though they come from the same Jira account as the operator's replies.
- **FR-015**: A comment MUST only decide a gate when its author is entitled:
  the reporter for requester gates (understanding, strategic interview,
  PRD), the change owner for CAB-1 and CAB-2. Authors are identified by
  their account, never by display name.
- **FR-016**: Every considered comment MUST pass kestrel's input screening
  before it can decide anything; a held comment decides nothing until the
  operator releases it.
- **FR-017**: The reply's meaning MUST be classified as approve, reject (with
  its reason), or unclear; unclear and reason-less rejections that need a
  reason MUST lead to a question back, never to a guess.
- **FR-018**: A decision from the ticket MUST resolve the gate exactly as the
  same decision in the kestrel UI does, and MUST record its author and
  channel.
- **FR-019**: Kestrel MUST confirm every decision, refusal, hold and
  "already decided" on the ticket.

## Success Criteria *(mandatory)*

- **SC-001**: A reporter and a change owner can take a request from ingested
  ticket to delivered change request without opening kestrel, except to
  answer interviews.
- **SC-002**: No comment kestrel posts to Jira shows raw markup.
- **SC-003**: Every gate opening produces exactly one ticket comment, and
  every reply is acted on at most once, including across restarts.
- **SC-004**: CAB members receive zero mentions from kestrel, and the status
  of an ingested issue is never changed by kestrel.
- **SC-005**: A reply from someone not entitled never changes a request.

## Assumptions

- There is no kestrel service account yet: kestrel posts through the
  operator's Jira account. Its comments are therefore recognised by their
  ownership marker, not by author, and replies are recognised by the
  plain-text `@kestrel` marker, not by a Jira mention. A service account
  comes later and would make both exact; it is not required here.
- The alpha's Jira is Cloud; Jira Server rendering is out of scope.
- New comments are found by polling at the existing poll interval; a reply
  may take that long to be acted on. No webhook.
- Alpha users may use the kestrel UI as a fallback; until OIDC (#79) they
  are trusted and the UI sits behind the operator's reverse proxy.
- **Known gap, deferred**: kestrel stays single-user (constitution
  Principle IV is not amended now). Letting the reporter and the change
  owner decide from the ticket is accepted as a known gap for the alpha,
  to be settled with the access & identity epic (#81). This feature
  supersedes spec 013 FR-006 ("approve only in kestrel's UI") for the
  ticket channel only.

## Out of Scope

- Answering interviews on the ticket (forms stay in kestrel; token links are
  #80).
- Mirroring decomposed tasks as Jira sub-tasks (#64) — the only place
  kestrel may ever transition anything — and completing manual tasks from
  the ticket.
- Jira webhooks; PR/MR review feedback (spec 044).
