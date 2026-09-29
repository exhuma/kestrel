# Feature Specification: Sub-tasks as cards inside the parent workflow

**Feature Branch**: `work`

**Created**: 2026-09-29

**Status**: Implemented (2026-09-29)

**Input**: GitHub #54 (epic #39), Vikunja task 708. It interacts with #51,
whose "manual tasks block downstream work" and "N manual tasks assigned to you"
parts feature 030 deliberately left for this feature.

## Context

kestrel models itself as a *department*. A request passes CAB-1, PRD sign-off
and CAB-2. At CAB-2 the operator approves a decomposition: a list of tasks,
each marked **coding** (agent-eligible) or **manual** (a human does it), and
each carrying an estimate (feature 030).

Today, approving CAB-2 does **not** put that work in front of the department.
kestrel publishes every approved task as a **new ticket** in the external task
source (GitHub or Jira). The poll or webhook loop then ingests each ticket
separately, and each becomes a workflow of its own, with its own branch and
its own draft pull request. The link back to the request is kept on the side.
Three things follow:

1. **One request produces several pull requests.** Nothing gathers the work
   for one request into a single change. Branch identity is per workflow, so
   the only way to get one PR out of several workflows would be new merge and
   conflict-handling machinery.
2. **One request looks like several requests.** A child is a first-class
   workflow, so it shows up as its own entry. Feature 029 had to add a parent
   link just to nest the children back under the request that produced them.
3. **Manual tasks sit outside the workflow.** Feature 030 publishes them with a
   marker so that ingestion never hands them to an agent. That keeps them from
   agents, but it also takes them out of view: kestrel cannot show them, count
   them, or wait for them.

This feature **reverses** shipped spec `012-task-decomposition-pipeline` on
this point. The approved tasks stay **inside the request's own workflow**, as
cards. One request → one workflow → one branch → one pull request, by
construction, and with no merge machinery: branch identity is already per
workflow, and delivery already updates an existing pull request rather than
opening a second one.

### Decisions settled before this spec (2026-09-29, with the developer)

- **Deterministic cards.** When CAB-2 is approved, kestrel itself turns the
  approved tasks into cards: one implementation card per coding task and one
  manual card per manual task. Task prerequisites become card dependencies. The
  coordinator does not choose, drop, merge or reword these cards: what runs is
  what the operator approved.
- **Manual cards are the operator's.** A manual card is resolved by the
  operator in the cockpit, in the same way as a gate. It blocks only the cards
  that list it as a prerequisite, and it blocks the request from being
  finished. It does **not** block delivery of the pull request.
- **Deliver once, at the end.** Each coding task is still verified on its own.
  kestrel creates the single delivery (push plus one draft pull request) only
  when every coding task has a clean verification.
- **Clean break on legacy data.** The child-ticket machinery is deleted, not
  kept dormant. Child tickets that are still open are closed or unlabelled by
  hand. Workflows that were already created from child tickets stay as
  ordinary workflows.
- **Accepted trade-off, for now: per-task tickets in Jira/GitHub are lost.**
  The request-level ticket remains, and the task breakdown is posted **once**,
  as one comment on the request's ticket. This is a known loss, not an
  endorsement. The task source is how people without kestrel access (for
  access or authorisation reasons, or a line manager) follow progress.
  Sub-tasks are expected to come back as *mirrors* of cards, never as
  ingestable requests, under the backlog epic #63 (bidirectional messaging
  between kestrel and the task source; sub-issues #64 and #65). They are
  deferred so as not to add churn while the board redesign (Vikunja 710)
  lands.

### Rejected alternative

Keep children as separate workflows, show the parent link to nest them in the
UI, and add an integration branch that merges the children's branches into
one pull request. This was rejected because it needs new merge and conflict
machinery to provide per-task traceability that a single-user tool does not
need.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Approved tasks become the request's own work (Priority: P1)

The operator approves CAB-2 on a decomposition of four coding tasks, where
task C needs A and B. Nothing new appears in GitHub or Jira apart from one
comment, and no new request appears on the stage board. The request's cockpit
now holds four implementation cards with the approved titles and bodies. A and
B are ready and C waits until both are done.

**Why this priority**: This is the reversal itself. Without it every other
story has nothing to act on.

**Independent Test**: Approve CAB-2 on a decomposition with a prerequisite
chain. Check that no ticket was created in the task source, that the workflow
holds one implementation card per coding task with the approved text, that the
dependency edges match the prerequisites, and that only cards with no open
prerequisites are ready.

**Acceptance Scenarios**:

1. **Given** an approved decomposition of *n* coding tasks, **When** CAB-2 is
   approved, **Then** the request's workflow gains exactly *n* implementation
   cards, and no ticket is created in the task source.
2. **Given** task C lists tasks A and B as prerequisites, **When** the cards are
   created, **Then** C's card depends on A's and B's cards and becomes ready
   only when both are done.
3. **Given** the cards were created, **When** the coordinator wakes up,
   **Then** it cannot remove, retitle or duplicate them. It can still add work
   of its own, as it can today.
4. **Given** CAB-2 approval is processed twice (for example a retried
   request), **When** the cards are created, **Then** each approved task still
   has exactly one card.
5. **Given** CAB-2 is approved, **When** the cards are created, **Then** kestrel
   posts one comment on the request's ticket that lists the approved tasks,
   each with its coding or manual classification.

---

### User Story 2 - One request, one pull request (Priority: P1)

The four implementation cards run one after another on the request's single
branch. Each is verified on its own. The request's draft pull request is
opened once, after the last coding task's verification comes back clean, and
it contains all four tasks' changes.

**Why this priority**: The single-PR gap is the reason for this feature. It
is P1 with Story 1 because the two only deliver value together.

**Independent Test**: Run a workflow with three coding tasks to delivery.
Check that exactly one branch and one pull request exist for the request, that
no pull request was opened before the last clean verification, and that the
pull request holds the changes of all three tasks.

**Acceptance Scenarios**:

1. **Given** three coding tasks, **When** the first two verify clean and the
   third has not, **Then** no delivery has happened yet.
2. **Given** every coding task has a clean verification, **When** the last one
   comes back clean, **Then** kestrel delivers exactly once: the branch is
   pushed and one draft pull request is opened.
3. **Given** a verification finds a problem, **When** the resulting remediation
   work is done and verified clean, **Then** that task counts as cleanly
   verified, and delivery waits for it until then.
4. **Given** two coding tasks with no dependency between them, **When** both
   are ready, **Then** they still run one at a time on the request's branch,
   never at the same time in the same working copy.

---

### User Story 3 - Manual tasks are visible, counted and waited on (Priority: P2)

The approved decomposition has three coding tasks and two manual tasks: "get
the vendor's API key" and "announce the change to the team". The coding task
that calls the vendor API lists the first manual task as a prerequisite. The
stage-board card for the request reads "2 manual tasks assigned to you". The
cockpit shows both manual cards, clearly marked as the operator's, each with a
way to mark it done. The vendor-API task waits for the API-key card. The other
coding tasks go ahead and the pull request is delivered. The request is not
shown as finished until the announcement card is marked done too.

**Why this priority**: This completes #51's intent: a workflow is not done
because the code is done. It depends on Stories 1 and 2, which give manual
tasks a place to live.

**Independent Test**: Approve a mixed decomposition. Check the stage-board
count, the cockpit marking, that a dependent coding task waits for its manual
prerequisite, that delivery is not held back by an unrelated open manual card,
and that the request is not finished until every manual card is done.

**Acceptance Scenarios**:

1. **Given** an approved decomposition with *m* manual tasks, **When** CAB-2 is
   approved, **Then** the workflow gains *m* manual cards that no specialist
   can ever claim.
2. **Given** *k* of those manual cards are still open, **When** the operator
   looks at the stage board, **Then** the request's card shows
   "*k* manual task(s) assigned to you". When *k* is zero, nothing is shown.
3. **Given** a coding task lists a manual task as a prerequisite, **When** the
   manual card is open, **Then** the coding card is not ready. When the
   operator marks the manual card done, the coding card becomes ready.
4. **Given** every coding task is cleanly verified and an unrelated manual card
   is still open, **When** the last verification comes back clean, **Then**
   the pull request is delivered anyway.
5. **Given** delivery has happened and a manual card is still open, **When**
   the operator looks at the request, **Then** it is not shown as finished.
   It becomes finished once the last manual card is marked done.
6. **Given** a manual card, **When** the operator opens it in the cockpit,
   **Then** they see the task's approved body and estimate and can mark it
   done. A task that turns out not to be needed is also marked done, because
   that is what releases its dependents.

---

### User Story 4 - The child-ticket machinery is gone (Priority: P3)

After the upgrade the operator sees no trace of the old model. No request
nests "children" on the board. Ingestion treats every ticket as a request in
its own right, and a ticket body no longer carries a marker that changes that.
Workflows that came from child tickets before the upgrade are still there as
ordinary requests.

**Why this priority**: It is clean-up. The feature works without it, but
leaving the machinery in place leaves two models of "a sub-task" in the code.

**Independent Test**: Upgrade a database that holds legacy child links and a
workflow that came from a child ticket. Check that the upgrade succeeds, that
the legacy workflow is listed as an ordinary top-level request, and that
ingesting a ticket whose body carries the old subtask marker starts an
ordinary, full request.

**Acceptance Scenarios**:

1. **Given** a database with legacy child links, **When** it is upgraded,
   **Then** the upgrade succeeds and those links no longer exist.
2. **Given** a workflow that was created from a child ticket, **When** the
   board is listed after the upgrade, **Then** it shows as an ordinary
   top-level request and goes through every gate its configuration requires.
3. **Given** a ticket whose body still carries the old subtask marker, **When**
   it is ingested, **Then** it becomes an ordinary request, the same as a
   ticket without the marker.

---

### Edge Cases

- **Decomposition with only manual tasks.** There is nothing to implement,
  verify or deliver. No delivery happens. The request is finished once every
  manual card is done.
- **Decomposition with a single task.** The same flow with one card. There is
  no special case for "nothing to split".
- **Prerequisite on a cancelled card.** The board counts a dependency as met
  only when the prerequisite is *done*. This feature does not change that rule.
  If the operator cancels a card through the generic intervention, its
  dependents keep waiting until the operator deals with them as well. For this
  reason manual cards offer "mark done", not "cancel" (FR-007).
- **Coding task depends on a manual task that is never done.** The coding card
  waits, so delivery cannot happen until the operator marks the manual card
  done. This is intended: the operator declared the dependency
  at CAB-2.
- **CAB-2 rejected.** No cards are created and no comment is posted. This is
  unchanged from today.
- **Decomposition gate approved before this upgrade whose children were never
  published** (for example the process stopped in between). It gets no
  children and no cards on its own. The operator re-runs decomposition or
  handles it by hand. A migration does not reconstruct it.
- **Comment posting fails.** Posting the breakdown to the task source fails
  (for example a network error). The cards still exist and work proceeds. The
  failure is retried and reported the same way as other write-backs to the
  task source. The ticket comment is informational and never gates work.
- **Workspace lease already held by another request on the same repository.**
  This is unchanged: the request's next implementation card waits for the
  lease, as today.
- **Coordinator proposes its own implementation card** (for example a fix it
  judged necessary). This is still allowed, as today. Delivery waits for every
  coding card, whoever created it, to have a clean verification. The one-PR
  guarantee holds either way.

## Requirements *(mandatory)*

### Functional Requirements

#### Materialising the approved decomposition

- **FR-001**: Approving CAB-2 MUST NOT create any ticket, sub-task or issue in
  the external task source.
- **FR-002**: Approving CAB-2 MUST create, inside the same workflow, exactly
  one implementation card per approved coding task and exactly one manual card
  per approved manual task. Each card MUST carry the approved task's title,
  body, classification and estimate.
- **FR-003**: Each approved prerequisite MUST become a dependency of the
  task's card on the prerequisite's card. A prerequisite can be a manual task
  or a coding task.
- **FR-004**: Card creation from an approved decomposition MUST be
  deterministic and idempotent. The coordinator MUST NOT be the one that
  decides which cards exist, and applying the same approval twice MUST NOT
  create duplicate cards.
- **FR-005**: The coordinator MUST NOT be able to cancel, retitle or re-scope a
  card created from an approved decomposition through its own actions. Only
  the operator's own interventions can do that. The coordinator MAY still
  create additional cards, subject to the existing gate rules.
- **FR-006**: When CAB-2 is approved, kestrel MUST post one comment on the
  request's ticket listing the approved tasks, each with its title and its
  coding or manual classification. The comment MUST be idempotent (posted once
  per approval) and MUST NOT gate any work.

#### Manual cards

- **FR-007**: A manual card MUST never be claimable by any specialist. Only the
  operator resolves it, by marking it done from the cockpit. The existing
  generic operator interventions still apply to it, unchanged.
- **FR-008**: An open manual card MUST block every card that depends on it, and
  it MUST keep the request from reaching its finished state. It MUST NOT, on
  its own, block delivery.
- **FR-009**: The stage board MUST show, on a request's card, the number of its
  manual cards that are still open, worded as "N manual task(s) assigned to
  you". It MUST show nothing when that number is zero.
- **FR-010**: The cockpit MUST show manual cards distinctly from agent work, as
  work for the operator. It MUST show each card's approved body and estimate,
  together with the action to mark it done.

#### Execution and delivery

- **FR-011**: Every coding task MUST be verified on its own after its
  implementation, as implementation cards are today.
- **FR-012**: kestrel MUST create the workflow's delivery only when every
  implementation card in the workflow is done and its latest verification is
  clean, with no remediation work outstanding. A clean verification of one
  task while others are unfinished MUST NOT deliver.
- **FR-013**: A workflow MUST deliver through exactly one branch and at most
  one change request. A later delivery for the same workflow (for example
  after a CI remediation) MUST update that change request, as today.
- **FR-014**: Implementation cards of one workflow MUST NOT run at the same
  time in the same working copy. They run one at a time, in an order that
  respects their dependencies, under the existing per-repository workspace
  serialisation.
- **FR-015**: A decomposition with no coding tasks MUST NOT produce a delivery.
  The request is finished once all its manual cards are resolved.

#### Removing the child-ticket model

- **FR-016**: The stored link between a request and its published child
  tickets MUST be removed, including any stored data, and so MUST the
  per-workflow "skip decomposition" flag.
- **FR-017**: Ingestion MUST treat every ticket as an ordinary request. The
  former subtask and manual-task markers in a ticket body MUST no longer
  change how it is ingested.
- **FR-018**: Nothing in the decomposition flow may call the task source's
  "create sub-task" capability any more. The capability itself and its
  per-source implementations are **kept**, unused, for reuse by #64.
  Deleting them now and re-adding them later would be churn.
- **FR-019**: The board listing MUST no longer expose a request's parent
  request, and the stage board MUST no longer nest one request inside another.
  This supersedes the "decomposition children" case of feature 029's FR-002
  and the parent link added by its FR-040. The frontend and backend halves of
  that contract change together (constitution Principle I).
- **FR-020**: Workflows already created from child tickets MUST keep working
  as ordinary requests after the upgrade. They are no longer exempt from any
  gate.
- **FR-021**: The per-child "created child task" write-back MUST be removed and
  replaced by the single breakdown comment of FR-006.

#### Documentation

- **FR-022**: Spec 012 MUST be marked as superseded by this feature on the
  child-ticket point, and the architecture notes MUST describe the one
  workflow, one branch, one PR model and the accepted loss of per-task tickets.

### Key Entities

- **Approved decomposition**: the CAB-2-approved candidate, a list of tasks,
  each with an identifier, title, body, classification (coding or manual),
  estimate, and prerequisites that name other tasks in the same list. It
  already exists (features 026 and 030). Only its effect changes.
- **Implementation card** (existing kind): now also created from an approved
  coding task. It records which approved task it came from, so creation can be
  idempotent and the cockpit can show the estimate.
- **Manual card** (new card kind): created only from an approved manual task.
  It is resolved only by the operator, never claimed, and it blocks its
  dependents and request completion.
- **Breakdown comment**: one write-back per approval to the request's ticket.
  It replaces the per-child write-backs.
- **Removed**: the child-task link records, the per-workflow skip-decomposition
  flag and the subtask marker. The task-source "create sub-task" capability is
  kept, unused (FR-018).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every request that reaches delivery, the task source and code
  host hold exactly one branch and at most one change request for it. That is
  zero extra pull requests per decomposed task, against *n* today.
- **SC-002**: Approving CAB-2 on an *n*-task decomposition creates zero tickets
  in the task source (against *n* today) and exactly one comment.
- **SC-003**: Every approved task is visible in the request's cockpit within
  one board refresh after CAB-2 approval, and the stage board shows exactly one
  card per request, with no nested children.
- **SC-004**: A request with at least one open manual card never shows as
  finished. The stage-board count of open manual cards is correct at all times
  (it matches the cockpit).
- **SC-005**: No specialist ever claims a manual card, and no implementation
  card starts before every one of its prerequisites is resolved. Both are
  covered by automated tests.
- **SC-006**: After the upgrade, the code base contains no reference to the
  child-task link, the skip-decomposition flag or the subtask marker, and
  nothing in the decomposition flow calls the create-sub-task capability. The
  dead-code checks in `task quality` pass.

## Assumptions

- **Verification per task is deterministic too.** Along with each
  implementation card created from an approved task, kestrel creates the
  verification that follows it, so "each coding task is verified on its own"
  does not depend on the coordinator choosing to add one. The plan settles the
  exact shape.
- **Remediation belongs to its task.** Work created from a verification finding
  counts towards the task it came from, so "every coding task is cleanly
  verified" can be judged per task. The plan settles how the link is recorded.
- **The existing per-repository workspace lease is the right granularity.** A
  request's cards all run on one branch in one working copy, so they must be
  serial anyway, and requests on different repositories still run in parallel.
  No new locking is introduced.
- **Legacy tickets are handled by hand.** Tickets published as children before
  the upgrade are not closed, unlabelled or migrated by kestrel. The operator
  is a single user and does this once. Until then, a labelled open child ticket
  that gets ingested becomes an ordinary new request.
- **Reset and clean-up.** A reset no longer has child tickets to clean up for
  new workflows. The breakdown comment is a kestrel-owned write-back and is
  cleaned up the same way as other kestrel comments (best-effort, per the
  constitution's clean-up constraint).
- **The phase projection stays display-only.** How manual cards show up in the
  10-phase spine is a display question. Per the locked decision on epic #40, it
  must not drive behaviour.

## Out of scope

- Recording actual usage and comparing estimates with actuals (#62).
- New personas or specialists.
- Any merge or integration-branch machinery (see *Rejected alternative*).
- Closing, unlabelling or migrating legacy child tickets in the external task
  sources.
- Mirroring cards back to the task source as sub-tasks, and resolving gates or
  manual tasks from the task source: backlog epic #63 (#64, #65).
- Editing an approved decomposition after CAB-2 (adding, removing or reordering
  tasks other than through operator interventions on individual cards).
