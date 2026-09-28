# Feature Specification: CAB-2 estimates, coding/manual split, and executive summary

**Feature Branch**: `work`

**Created**: 2026-09-28

**Status**: Implemented (2026-09-28)

**Input**: GitHub #50 (resource-cost estimation), #51 (coding vs non-coding
classification), #52 (CAB-2 executive summary), Vikunja task 707. Also the
"Original request" field for the request cockpit, which was deferred from
feature 029 to this task (see 029 `tasks.md`, the FR-039 finding).

## Context

kestrel models itself as a *department*. A request passes three human gates:
CAB-1 (strategic go/no-go), PRD sign-off, and CAB-2. CAB-2 is the last
decision before agents start spending on implementation. Today it shows the
operator only a raw list of the tasks the `pm` proposed. There is no size, cost
or effort figure, no indication of which tasks an agent can do at all, and no
summary. The operator has nothing to weigh, so CAB-2 is a rubber stamp.

This feature gives CAB-2 something to decide on:

1. The `pm` marks each proposed task as **coding** (agent-eligible) or
   **manual** (a human does it) and writes a short executive summary.
2. A separate specialist, **Engineering** (`developer`), then **estimates**
   every task: size, confidence, human effort, agent token usage, review
   effort, risks, and a rationale. The pm proposes the scope and the developer
   estimates it, so the agent that sets the scope is not the one that prices it.
3. kestrel **aggregates** the estimates into totals with plain arithmetic, not
   an LLM. It attaches the result, the pm's prose and the per-task figures to
   the CAB-2 gate as one executive summary.

Estimates are produced by agents and are **untrusted**. The developer accepts
that they may be off by an order of magnitude at first. They are captured both
to inform the CAB-2 decision and so that the agentic workflow can later be
evaluated against actual usage. Recording actual usage is a separate follow-up
(see Out of scope).

Prior art: `specs/016-cab-estimates` was written for the old fixed driver and
never built on the board. Its intent carries over: per-task estimates, totals
at the gate, no go/no-go recommendation from the system. Its mechanism does not
carry over (tracker comments, model catalogue).

### Decisions settled before this spec (2026-09-28, with the developer)

- Estimate unit: size S/M/L/XL **plus** confidence, man-hours, token usage,
  risk flags, human-review effort and a one-line rationale. Model
  recommendations (spec 016) are dropped.
- Estimator: a separate specialist, `developer`, on a new estimation step.
- Classifier: the `pm`, while decomposing.
- Executive summary: prose from the `pm`, totals computed by code.
- Coding/manual enforcement in this feature: classify, display, and make sure
  no agent can ever claim a manual task. Blocking downstream work on manual
  tasks is deferred to GitHub #54.
- Actual usage and estimate-vs-actual comparison: a separate follow-up.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Decide CAB-2 on an executive summary (Priority: P1)

A request has passed PRD sign-off and been decomposed. The operator opens the
request, sees that CAB-2 is waiting, and reads an executive summary. It has a
short prose overview of the proposed work, totals (how many tasks of each
size, total human-equivalent hours, total agent tokens, total review hours,
how many estimates are low-confidence), the split between coding and manual
tasks, and the risks named. Below that is one row per task with its figures
and rationale. Everything is labelled as an agent estimate. The operator
approves or rejects exactly as before.

**Why this priority**: This is the reason for the feature. Without it CAB-2
cannot be a real go/no-go.

**Independent Test**: Drive a request through decomposition and estimation
using scripted agent outputs. Open the CAB-2 gate and check that the summary
is available and that its totals equal the sums of the per-task figures.

**Acceptance Scenarios**:

1. **Given** a valid decomposition of three tasks and valid estimates for all
   three, **When** the CAB-2 gate appears, **Then** the operator can read, from
   the gate, an executive summary containing the pm's prose, the totals, the
   coding/manual split, the named risks and one row per task.
2. **Given** tasks sized S, S and L, with man-hours 2, 3 and 16, **When** the
   summary is built, **Then** it shows "2×S, 1×L" and 21 man-hours. These
   figures are computed, not written by an agent.
3. **Given** one estimate with low confidence, **When** the summary is shown,
   **Then** that is counted and visible in the totals as well as in that task's
   row.
4. **Given** the summary is on screen, **When** the operator looks at any
   estimate figure, **Then** it is marked as agent output and never as
   operator-approved or fact.
5. **Given** the operator approves CAB-2, **When** approval completes, **Then**
   the tasks are published exactly as before this feature, apart from the
   manual-task handling in User Story 2.

---

### User Story 2 - Manual tasks are never handed to an agent (Priority: P1)

The pm's decomposition may contain tasks an agent cannot do: get a sign-off,
update a vendor contract, change a DNS record at a provider with no API. The
pm marks them as manual. The operator sees them marked as manual in the
summary and the gate. After approval they are published as tracker sub-tasks
like every other task, but kestrel never turns them into agent workflows.

**Why this priority**: #51 requires that non-coding tasks are "never claimed by
a specialist". Without the guard, an approved manual task becomes a coding
workflow, and an agent would try to "implement" a legal sign-off.

**Independent Test**: Approve a decomposition with one coding and one manual
task. Let ingestion see both published sub-tasks. Only the coding one becomes a
workflow, and no card is ever created for the manual one.

**Acceptance Scenarios**:

1. **Given** a decomposition with tasks classified coding and manual, **When**
   the summary is shown, **Then** each task shows its classification and the
   totals show the count of each.
2. **Given** CAB-2 approval, **When** tasks are published, **Then** a manual
   task is published with a marker that identifies it as manual, and its
   published body says it is for a human.
3. **Given** a published manual sub-task, **When** ingestion observes it,
   **Then** no workflow is started for it, now or on any later poll.
4. **Given** a decomposition where every task is manual, **When** it passes
   through estimation and CAB-2, **Then** the summary is produced normally and
   approval publishes the tasks, but no agent workflow results.

---

### User Story 3 - Estimates from a separate specialist (Priority: P1)

After the pm's decomposition is accepted, the Engineering specialist receives
an estimation card. It sees the approved PRD, the request and the proposed
tasks, and has read-only access to the repository so it can size tasks against
the real code. It returns one estimate per proposed task. kestrel validates
the result and, only if it is complete and valid, builds the summary and opens
the CAB-2 gate.

**Why this priority**: The developer chose a separate estimator so that the
agent that sets the scope is not also the one that prices it. It is a
prerequisite for User Story 1.

**Independent Test**: With a scripted decomposition, check that an estimation
card appears for Engineering, that no CAB-2 gate exists until it completes,
and that a valid estimation result creates exactly one gate.

**Acceptance Scenarios**:

1. **Given** a valid decomposition, **When** it is accepted, **Then** an
   estimation card becomes ready for Engineering, and no CAB-2 gate exists yet.
2. **Given** an estimation result that covers every proposed task with valid
   values, **When** it is accepted, **Then** exactly one CAB-2 gate is created,
   carrying the executive summary.
3. **Given** an estimation result that omits a task, estimates a task that was
   not proposed, or has a missing or out-of-range value, **When** it is
   accepted, **Then** no CAB-2 gate is created. A coordinator-review card
   records the problem, the same as an unparseable decomposition today.

---

### User Story 4 - Read the original request in the cockpit (Priority: P2)

In the request cockpit, the operator opens "Original request" from the
artifact rail and reads the request as kestrel received it. A note makes clear
that this is the text screened at intake, and that later edits to the source
ticket are not reflected.

**Why this priority**: The rail currently says "Not yet produced" about the one
artifact that certainly was produced. The operator accepted that as an interim
state, and this closes it. It does not depend on User Stories 1–3.

**Independent Test**: Load the cockpit for a workflow with a non-empty request
body. "Original request" is available, opens to the body text, and shows the
freshness note and no trust chip.

**Acceptance Scenarios**:

1. **Given** a workflow whose request body is non-empty, **When** the cockpit
   loads, **Then** the "Original request" rail entry is available and opens to
   that text.
2. **Given** a workflow whose request body is empty, **When** the cockpit
   loads, **Then** the entry shows as not produced.
3. **Given** the original request is open, **When** it is displayed, **Then**
   it carries a freshness note and no trust chip.
4. **Given** the board listing (all workflows), **When** it is fetched, **Then**
   it does not include request bodies.

### Edge Cases

- **Decomposition without classification or summary**: a new-format
  decomposition that lacks a task's classification, or lacks the summary
  prose, is invalid. It fails closed like any other invalid decomposition: no
  estimation card and no gate.
- **Tasks without identifiers**: estimates must be matched to tasks without
  guessing. If the pm gives no identifier for a task, kestrel assigns a stable
  one before estimation, and the estimator sees and uses it.
- **Duplicate task identifiers** in a decomposition make it invalid.
- **Manual tasks and tokens**: a manual task's agent token estimate and review
  effort are zero by definition. A non-zero value there is invalid, not
  silently ignored.
- **Coding task with zero man-hours or zero tokens**: invalid. Every coding
  task costs something.
- **Estimation retries**: if the estimation card fails and is retried, only the
  estimation that is finally accepted produces a summary and a gate. A workflow
  never gets two CAB-2 gates from one decomposition.
- **CAB-2 rejected**: behaviour is unchanged from today. This feature adds no
  redraft loop.
- **Gates already open when this ships**: a CAB-2 gate created before this
  feature has no summary. It remains approvable, and its tasks are published
  as coding tasks, as they are today.
- **Summary prose that argues for a decision**: the pm is instructed not to
  recommend go/no-go. kestrel cannot enforce this mechanically, so the prose is
  displayed as agent output.
- **Very long request bodies**: the original request opens in a scrollable
  reader and is never truncated silently.

## Requirements *(mandatory)*

### Functional Requirements

#### Decomposition (pm)

- **FR-001**: Each task in a decomposition MUST carry a classification,
  `coding` or `manual`. Only `coding` tasks are eligible for agent work.
- **FR-002**: A decomposition MUST carry executive-summary prose of 1–2
  paragraphs, written for a non-technical decision-maker. The pm MUST be
  instructed that this prose describes the work and does not recommend a
  decision.
- **FR-003**: Every task in an accepted decomposition MUST have an identifier
  that is unique within the decomposition. When the pm omits one, kestrel MUST
  assign one deterministically before estimation.
- **FR-004**: A decomposition that violates FR-001 to FR-003 (missing
  classification, missing prose, duplicate identifier) MUST fail closed the
  same way an unparseable decomposition does today.

#### Estimation (developer)

- **FR-005**: When a decomposition is accepted, kestrel MUST create an
  estimation card for the Engineering specialist instead of creating the CAB-2
  gate directly.
- **FR-006**: The estimation card MUST give the specialist the request, the
  approved PRD (when there is one), and the proposed tasks with their
  identifiers and classifications. It MUST have read-only access to the
  repository.
- **FR-007**: The estimation result MUST contain exactly one estimate for each
  proposed task. Each estimate has:
  - size: one of S, M, L, XL;
  - confidence: one of low, medium, high;
  - man-hours: the effort for a human to complete the task by hand;
  - agent tokens: the expected total token usage for an agent to complete it;
  - review hours: the human effort to review the agent's result;
  - risk flags: a short list of named risks, which may be empty;
  - rationale: one line explaining the estimate.
- **FR-008**: Man-hours MUST be positive for every task. For coding tasks,
  agent tokens and review hours MUST be positive. For manual tasks they MUST be
  zero.
- **FR-009**: An estimation result that violates FR-007 or FR-008 MUST create no
  CAB-2 gate. It MUST instead produce a coordinator-review card describing the
  problem, the same way an unparseable decomposition does.

#### Executive summary and CAB-2

- **FR-010**: When a valid estimation result is accepted, kestrel MUST build an
  executive summary without an LLM. It contains:
  - the pm's prose;
  - the count of tasks per size;
  - total man-hours, total agent tokens and total review hours;
  - the number of low-confidence estimates;
  - the number of coding and manual tasks;
  - the distinct risk flags with the tasks they apply to;
  - one row per task with its title, classification and every estimate field.
- **FR-011**: kestrel MUST then create the CAB-2 gate (the existing
  decomposition gate: no new gate kind, same approve/reject meaning) and make
  the executive summary readable from it before the operator decides.
- **FR-012**: The executive summary MUST be stored as a durable artifact with
  the agent-output trust level, and MUST fill the request cockpit's
  "Executive summary" rail entry.
- **FR-013**: Wherever an estimate or the summary is shown, it MUST be
  identified as an agent estimate. It MUST never be presented as
  operator-approved.
- **FR-014**: The executive summary MUST contain no go/no-go recommendation
  produced by kestrel itself.
- **FR-015**: The CAB-2 gate's title MUST state the coding/manual split (e.g.
  "Approve decomposition (3 coding, 1 manual)").
- **FR-016**: The estimates MUST be stored in a structured, machine-readable
  form, keyed by workflow and task identifier. A later feature must be able to
  compare them with actual usage without parsing prose.

#### Publishing after approval

- **FR-017**: On CAB-2 approval, each task MUST be published as it is today.
  Additionally:
  - a manual task MUST carry a marker that identifies it as manual;
  - every published task's body MUST include its approved estimate, so a human
    picking it up sees the figures.
- **FR-018**: Ingestion MUST never start a workflow for a published task that
  carries the manual marker. This is the guard that keeps a manual task from
  ever being claimed by a specialist.
- **FR-019**: A decomposition approved on a gate created before this feature
  (no classification, no estimates) MUST publish as it does today: every task
  treated as coding, with no estimate section.

#### Original request

- **FR-020**: The single-workflow board snapshot MUST include the workflow's
  request body as screened at intake. The workflow listing MUST NOT include it.
  Both sides of the type contract change together (constitution Principle I).
- **FR-021**: The cockpit's "Original request" rail entry MUST be available when
  the request body is non-empty, and MUST open it in a reader.
- **FR-022**: The original request MUST show a freshness note ("screened once at
  intake; later edits to the source ticket are not reflected here") and MUST NOT
  show a trust chip.
- **FR-023**: Intake MUST NOT begin writing an artifact for the request body.
  The body is read from the workflow directly.

#### Boundaries

- **FR-024**: This feature MUST NOT make manual tasks block downstream work, add
  a "manual tasks assigned to you" count to the stage board, or record actual
  usage. Those belong to GitHub #54 and to the follow-up issue.
- **FR-025**: The phase projection MUST stay display-only (spec 026 FR-037).
  Estimation is shown within the existing "Technical analysis" phase, and CAB-2
  keeps its phase.

### Key Entities

- **Classified task**: a proposed task with an identifier, title, body,
  prerequisites (unchanged) and a classification, coding or manual.
- **Task estimate**: the FR-007 fields for one task, keyed by that task's
  identifier within one workflow's decomposition. Agent output, untrusted.
- **Executive summary**: a durable, agent-output artifact combining the pm's
  prose, computed totals and per-task rows for one decomposition. It is read
  at CAB-2.
- **Manual marker**: a marker on a published sub-task telling ingestion that it
  is for a human and must never become an agent workflow.
- **Original request**: the workflow's request body, screened at intake and
  frozen after that. It is not an artifact.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of new-format decompositions that reach CAB-2, the
  operator can read an executive summary from the gate before deciding.
- **SC-002**: For 100% of summaries, every total equals the sum or count of the
  per-task figures it is derived from.
- **SC-003**: 0 agent workflows are ever started for a task published as manual.
- **SC-004**: 0 CAB-2 gates are created from an estimation result that does not
  cover every proposed task exactly once.
- **SC-005**: For 100% of workflows with a non-empty request body, the operator
  can open the original request from the cockpit in one click.
- **SC-006**: An operator can see the coding/manual split and the total
  human-equivalent hours for a request without opening any artifact other than
  the executive summary.

## Assumptions

- The estimation step runs only when decomposition runs, which is gated by the
  existing decomposition-required setting. No new setting is introduced.
- The `developer` specialist gains the estimation card kind. No new specialist
  role is created.
- Token estimates are total tokens (input and output) and are not converted to
  money. Pricing differs per backend, and the Claude CLI subscription and the
  self-hosted LLM have no per-token price.
- Man-hours mean one competent developer who knows the codebase, working by
  hand without an agent. Review hours are separate and are not counted in
  man-hours.
- Size buckets are chosen by the estimator. They are not derived from
  man-hours, and they are not validated against man-hours.
- The executive summary is plain text or Markdown, readable in the cockpit's
  existing artifact reader.

## Out of scope

- Recording actual usage per attempt (tokens, cost, wall-clock) and an
  estimate-vs-actual view. This will be filed as its own GitHub issue.
- Manual tasks blocking downstream work, and the stage-board count of manual
  tasks (GitHub #54, Vikunja 708).
- A redraft loop on CAB-2 rejection.
- Per-task model recommendations and backend model catalogues.
