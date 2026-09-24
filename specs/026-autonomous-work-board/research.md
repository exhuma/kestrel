# Research: Autonomous Work Board

## Decision: Use a durable board aggregate, not a configurable step pipeline

**Rationale**: The feature requires independent specialist ownership, explicit
dependencies, reconciliation, bounded retries, and different waiting reasons.
A positional workflow-step record cannot represent this without retaining a
hidden strict pipeline. A card/dependency model makes readiness and invalidation
explicit and lets the coordinator react to events rather than own a live loop.

**Alternatives considered**:

- Extend the current six-step driver with optional branches. Rejected because
  `continue_run()` and positional `run.steps` remain the real authority.
- Permit every specialist to create and advance work. Rejected because it
  weakens scope, source-write, and write-lease authority.
- Build a generic workflow language. Rejected as premature abstraction for one
  single-user product.

## Decision: Separate deterministic policy from agent decisions

**Rationale**: A coordinator may propose useful routing or reconciliation, but
must not grant itself an unsafe role, permission, source update, scope change,
or transition. The board policy is the only mutation authority and validates
coordinator actions, router interventions, claims, and recovery consistently.

**Alternatives considered**:

- Encode all restrictions in prompts. Rejected because prompts cannot enforce
  persistence, source ownership, or concurrency safety.
- Put policy in routers. Rejected because pollers, recovery, and coordinator
  dispatch would bypass it.

## Decision: Use short durable claim and repository-write leases

**Rationale**: Existing backend semaphores control adapter capacity but cannot
recover ownership after restart. Durable expiry-based claims permit bounded
retry
and make one repository writer enforceable across all board workers.

**Alternatives considered**:

- In-memory asyncio locks. Rejected because they disappear on restart.
- One active workflow per repository. Rejected because read-only work should
  proceed independently.
- Multiple writer worktrees. Deferred because merge/reconciliation policy would
  add complexity beyond the first board release.

## Decision: Persist versioned handoff artifacts outside project commits by
default

**Rationale**: Recovery requires durable handoffs regardless of card type, while
the project must not receive Kestrel-only operational files. A content reference
and immutable metadata record preserves provenance and allows delivery to select
only explicitly material artifacts.

**Alternatives considered**:

- SQLite text columns only. Rejected because large bodies inflate database and
  SSE payloads.
- Git commits as every handoff. Rejected because operational state would pollute
  target projects.
- The current `.kestrel/` behavior for all handoffs. Rejected because it
  commits artifacts that are only needed by Kestrel.

## Decision: Use a fail-closed input intake and quarantined security review

**Rationale**: Current feedback, task bodies, gate input, and questionnaire
answers can reach prompts or source writes. Authenticity, marker, and dedup
checks do not establish content safety. A common intake records a bounded input,
applies deterministic checks, invokes only a constrained input-security role,
and quarantines uncertainty before any other side effect.

**Alternatives considered**:

- Let the coordinator judge raw input. Rejected because it combines untrusted
  content with high workflow authority.
- Run a security role after normal ingestion. Rejected because unsafe text has
  already reached persistence, prompts, or acknowledgements.
- Auto-discard suspect inputs. Rejected because an operator needs an auditable
  release/discard decision.

## Decision: Keep direct operator prompts outside automatic quarantine

**Rationale**: A direct session prompt intentionally addresses an agent. It
still receives bounds and an explicit injection-risk confirmation record, but
automatic quarantine would degrade the direct-dispatch utility.

**Alternatives considered**:

- Trust direct prompts without warning. Rejected because they may contain copied
  untrusted data.
- Apply full source-input quarantine. Rejected by the operator decision.

## Decision: File-backed specialist definitions with strict validation

**Rationale**: Named operator-owned role folders make prompts and companion
guidance inspectable and updateable without shipping executable plugins. A
validated manifest preserves backend capability, workspace, and retry limits.

**Alternatives considered**:

- Static Python profile registry. Rejected because it conflates interview
  personas and autonomous execution roles.
- Runtime-created coordinator roles. Rejected because roles could bypass policy.
- Executable plugins. Rejected because they expand the existing hooks trust
  boundary and are unnecessary for the first release.

## Decision: Use selective external projections with an idempotency ledger

**Rationale**: Task sources have incompatible Kanban primitives and public
history is forward-only. The board remains authoritative while durable,
idempotent projections publish only gates, blockers, approved artifacts, child
work, and delivery. The same records establish cleanup ownership.

**Alternatives considered**:

- Synchronize every card state. Rejected due to tracker noise and mismatched
  external capabilities.
- Delivery-only updates. Rejected because human gates and escalations need a
  source-facing path.

## Decision: Use a Vuetify Board/List plus a read-only Vue Flow graph

**Rationale**: State-grouped board/list views support scanning and keyboard use.
The dependency graph exposes fan-out, bottlenecks, reconciliation, and ownership
that columns cannot show. Vue Flow supports Vue 3, TypeScript, custom nodes, and
controlled read-only graph state; Kestrel's Vue 3.5 is compatible.

**Alternatives considered**:

- Vue Flow alone. Rejected because canvas interaction is not the complete
  accessible operator experience.
- A drag-and-drop Kanban library. Rejected because arbitrary movement violates
  backend transition policy.
- Persisted graph positions and a graph layout dependency. Deferred; a
  deterministic local depth layout is sufficient until usability evidence says
  otherwise.

## Decision: Treat verifier findings by authority boundary

**Rationale**: An approved PRD permits internal remediation of implementation
nonconformance. Ambiguity, contradiction, infeasibility, and material risk need
coordinator review and sometimes a human decision. This retains autonomy where
scope is known and protects requester authority where it is not.

**Alternatives considered**:

- Escalate every verification failure. Rejected because it defeats autonomous
  remediation.
- Let verifier edit the PRD. Rejected because it bypasses scope approval.
