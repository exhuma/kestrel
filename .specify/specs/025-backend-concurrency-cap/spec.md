# Feature Specification: Backend Concurrency Cap and Rate-Limit Backoff

**Feature Branch**: `025-backend-concurrency-cap`

**Created**: 2026-09-22

**Status**: Draft

**Input**: User description: "A configurable per-backend LLM concurrency cap
(global across all workflow runs and ad-hoc sessions, default 1) plus
rate-limit-aware retry with backoff in the OpenCode backend, so that a task
source firing off multiple workflows cannot exhaust provider rate limits."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Provider rate limits survive workflow fan-out (Priority: P1)

An operator runs kestrel against a rate-limited LLM provider (for example an
Azure OpenAI deployment behind the OpenCode backend). The task source
generates multiple candidate tasks, each of which starts its own workflow.
Each workflow also fans out internally (interview refine steps run one turn
per profile slot concurrently; reconcile and critic steps add more turns).

Today all of those turns race to the provider at once and the provider
responds with HTTP 429 in rapid succession, so many turns fail or waste time.

With this feature, every LLM turn dispatched through a configured backend is
admitted by that backend's concurrency cap. With the default configuration
the cap is one: at most one in-flight LLM call per configured backend at any
moment, regardless of how many workflows or profile slots are running.
Turns beyond the cap queue and start as soon as a slot frees.

**Why this priority**: This is the core problem being solved. Without it,
multi-workflow runs against a rate-limited provider are unreliable.

**Independent Test**: Configure one backend with `max_concurrency = 1`,
start two workflows that each issue at least two turns to that backend, and
observe that no more than one request to the provider is in flight at any
moment while all turns eventually complete. Repeat with
`max_concurrency = 3` and observe up to three concurrent requests.

**Acceptance Scenarios**:

1. **Given** a backend configured with `max_concurrency = 1`, **When** two
   workflows each issue a turn to that backend, **Then** the second turn
   waits until the first completes before its provider call starts.
2. **Given** a backend configured with `max_concurrency = 3`, **When** five
   turns are issued concurrently to that backend, **Then** at most three
   provider calls are in flight simultaneously and all five complete.
3. **Given** two differently configured backends, **When** turns are issued
   to both, **Then** each backend's cap is enforced independently; a busy
   slot on one backend does not delay turns on the other.
4. **Given** an ad-hoc (non-workflow) session and a workflow session both
   using the same backend, **When** both issue turns concurrently, **Then**
   they share the same cap for that backend.

---

### User Story 2 - Transient rate-limit rejections are retried with backoff (Priority: P1)

Even with the cap, a provider may still reject a request with HTTP 429
(rate limit exceeded), for example because of shared quota or burst limits.
Today such a rejection fails the turn immediately.

With this feature, when the OpenCode backend receives a rate-limit response,
it retries the same turn automatically: it honors the provider's
`Retry-After` header when present, otherwise it waits an exponentially
growing delay (starting from a configurable base) with jitter, up to a
configurable number of retries. After the retries are exhausted, the turn
fails with a concise diagnostic that identifies the rate limit as the cause.

**Why this priority**: The cap prevents self-inflicted throttling; backoff
handles residual provider-side throttling so individual turns do not fail on
a transient 429.

**Independent Test**: Point the OpenCode backend at a stub that returns 429
twice (once with `Retry-After`, once without) and then succeeds, and observe
that the turn completes after two retries with the expected waits. Make the
stub always return 429 and observe that the turn fails after the configured
number of retries with a rate-limit diagnostic.

**Acceptance Scenarios**:

1. **Given** a backend whose provider returns 429 with `Retry-After: 2`,
   **When** a turn is issued, **Then** the backend waits approximately two
   seconds and retries; if the retry succeeds the turn completes normally.
2. **Given** a backend whose provider returns 429 without `Retry-After`,
   **When** a turn is issued, **Then** the backend waits an exponentially
   growing delay (base × 2^attempt, with jitter) and retries.
3. **Given** the configured retry count is N, **When** the provider returns
   429 for every attempt, **Then** the turn fails after exactly N retries
   with a diagnostic that names rate limiting as the cause.
4. **Given** the provider returns a non-rate-limit error (for example HTTP
   500), **When** a turn is issued, **Then** no retry is performed and the
   existing error behavior applies.

---

### User Story 3 - Operator can tune the cap and backoff per backend (Priority: P2)

An operator configures kestrel in `config.toml`. Each configured backend
gains three optional settings:

- `max_concurrency` — maximum in-flight LLM calls for this backend
  (positive integer, default 1);
- `rate_limit_retries` — maximum retries after a rate-limit rejection
  (non-negative integer, default 3);
- `rate_limit_backoff_seconds` — base delay for exponential backoff when the
  provider gives no `Retry-After` (positive number, default 2.0).

Settings are validated at startup: non-positive or otherwise invalid values
are rejected with a clear configuration error. The example config file and
the backend/configuration documentation describe all three settings, their
defaults, and an Azure-style rate-limit scenario.

**Why this priority**: Tunability is what makes the feature operable across
different providers and quotas; it depends on the cap and backoff existing.

**Independent Test**: Start kestrel with each of the three fields set to
invalid values (zero, negative, non-numeric) and observe a clear startup
error naming the field; start with valid custom values and observe them take
effect (cap enforced at the new value, backoff base used on 429 without
`Retry-After`).

**Acceptance Scenarios**:

1. **Given** `max_concurrency = 0` in the config, **When** kestrel starts,
   **Then** startup fails with an error naming `max_concurrency`.
2. **Given** `rate_limit_retries = -1`, **When** kestrel starts, **Then**
   startup fails with an error naming `rate_limit_retries`.
3. **Given** a backend entry without any of the three fields, **When**
   kestrel starts, **Then** it runs with defaults 1 / 3 / 2.0 and existing
   behavior is otherwise unchanged.
4. **Given** the example config file, **When** an operator reads it, **Then**
   all three fields are documented with their defaults and meaning.

---

### Edge Cases

- What happens when a turn is cancelled (user stops the session) while it is
  waiting for a concurrency slot? The wait must be interruptible: the turn is
  abandoned without starting its provider call, and the slot is not consumed.
- What happens when `max_concurrency` is larger than any realistic fan-out?
  Behavior is identical to today (no queueing observed).
- What happens when the provider returns 429 with a non-numeric or absurdly
  large `Retry-After`? The backend falls back to its exponential schedule
  instead of sleeping on garbage.
- What happens when multiple workflows target the same backend while another
  workflow targets a different backend? Caps are independent per backend;
  total in-flight calls across backends may exceed any single cap.
- The cap is process-global: it covers all workflow runs and ad-hoc sessions
  inside one kestrel process. Multiple kestrel processes each enforce their
  own cap; cross-process coordination is out of scope.
- A turn waiting for its backend permit is shown as queued, using a `💤`
  marker, rather than as actively running. When the permit is acquired it
  changes to running; cancellation or failure while queued changes it to an
  error state.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST limit in-flight LLM calls per configured
  backend to the value of that backend's `max_concurrency` setting, applied
  globally across all workflow runs and ad-hoc sessions within one kestrel
  process.
- **FR-002**: The default value of `max_concurrency` MUST be 1 when the
  field is absent from the configuration.
- **FR-003**: Turns that cannot obtain a concurrency slot MUST queue and
  start in order as slots free, without failing or timing out solely because
  they waited.
- **FR-004**: Concurrency caps of different backends MUST be independent;
  one backend's queue MUST NOT delay another backend's turns.
- **FR-005**: A turn waiting for a slot MUST be cancellable: cancellation
  while queued abandons the turn without starting its provider call.
- **FR-006**: The OpenCode backend MUST retry a turn when the provider
  responds with HTTP 429, up to `rate_limit_retries` retries (default 3).
- **FR-007**: When the 429 response carries a valid positive `Retry-After`
  header, the backend MUST wait that many seconds before retrying; otherwise
  it MUST wait an exponentially growing delay starting from
  `rate_limit_backoff_seconds` (default 2.0) with jitter.
- **FR-008**: When retries are exhausted, the turn MUST fail with a concise
  diagnostic identifying rate limiting as the cause.
- **FR-009**: Responses other than rate-limit rejections MUST NOT be retried
  by this mechanism; their existing error behavior is unchanged.
- **FR-010**: `max_concurrency` MUST be validated as a positive integer,
  `rate_limit_retries` as a non-negative integer, and
  `rate_limit_backoff_seconds` as a positive number at configuration load;
  invalid values MUST fail startup with an error naming the offending field.
- **FR-011**: The example configuration file and the backend/configuration
  documentation MUST document all three fields, their defaults, and a
  rate-limit scenario.
- **FR-012**: The system MUST log every provider rate-limit rejection through
  Python's logging framework, including retry position, retry budget, chosen
  delay, and whether the delay came from `Retry-After` or exponential
  fallback; retry exhaustion MUST be logged as an error without exposing
  prompts, credentials, headers, or response bodies.
- **FR-013**: A workflow chip waiting for a backend concurrency permit MUST
  report status `queued` and display `💤`; it MUST change to `running` once
  admitted and MUST remain distinct from an actively running chip.
- **FR-014**: A persisted Kestrel-generated child task MUST skip describe,
  refine, and technical analysis, because its generated body is already the
  parent-approved implementation scope; ordinary sentinel-bearing tasks keep
  their existing approval behavior.
- **FR-015**: A blank backend exception MUST become a non-empty session and
  workflow diagnostic, and the backend MUST log the missing diagnostic as an
  error.

### Key Entities

- **Backend configuration entry**: one per configured LLM backend; gains the
  three optional tuning fields above alongside the existing type/base-url/
  model settings.
- **Concurrency slot**: an abstract permit owned by a backend; at most
  `max_concurrency` permits are held at once per backend.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With two workflows issuing turns to one default-configured
  backend, the number of simultaneously in-flight provider calls never
  exceeds 1.
- **SC-002**: With `max_concurrency = 3` and five concurrent turns, at most
  3 provider calls are in flight at any moment and all 5 turns complete.
- **SC-003**: A turn that receives two consecutive 429 responses (one with
  `Retry-After`, one without) and then a success completes successfully
  after the configured waits, instead of failing.
- **SC-004**: A turn against a provider that always returns 429 fails after
  exactly the configured number of retries, with a diagnostic naming rate
  limiting.
- **SC-005**: Startup with any invalid value for the three new fields fails
  fast with an error message that names the field; startup with no fields set
  succeeds and behaves as before.

## Assumptions

- The cap is enforced inside one kestrel process (process-global). Running
  multiple kestrel processes against the same provider multiplies effective
  concurrency; cross-process coordination is out of scope for this feature.
- Rate-limit retry logic is implemented in the OpenCode backend, where the
  observed Azure throttling occurs. The other backends receive the
  concurrency cap (FR-001..FR-005) but no new retry policy in this change.
- `Retry-After` is interpreted as seconds when numeric; header values that
  are non-numeric or not positive fall back to the exponential schedule.
- Jitter on the exponential delay is small (a fraction of the computed wait)
  and its exact distribution is an implementation detail.
- Waiting for a concurrency slot does not count against any existing turn
  timeout; only the provider call itself is bounded by existing timeouts.
