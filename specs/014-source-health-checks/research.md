# Research: Source Health Checks

## R1 — Where the capability lives: existing ports, not a new one

**Decision**: Add `async def check_health(self) -> bool` to both the
`TaskSource` and `CodeHost` protocols (`backend/app/ports.py`). Each
adapter (GitHub, Jira, GitLab, Gitea, fixture) implements it with its own
cheapest authenticated, repo/ticket-independent read.

**Rationale**: The requester explicitly asked for this to be "abstracted
on the existing port," and issue #37 (the proposed future `FeedbackSource`
port) already exists to track a *third* port; this feature does not wait
on that redesign, it just adds one capability method that a future
`FeedbackSource` adapter can implement the same way once #37 lands.

**Alternatives considered**: A standalone `Healthcheckable` port
mirroring the `Acknowledgeable` protocol added in feature 013. Rejected —
`Acknowledgeable` exists because a single piece of `Feedback` is handed
to *either* a `TaskSource` or a `CodeHost` at runtime, so a shared
structural type was needed for that call site. Health checks have no such
call site: every adapter is checked directly, by whichever concrete
object bootstrap already holds a reference to. A shared protocol would
add a name with no behavior attached to it.

**Not reused**: `CodeHost.get_default_branch(repo)`, despite its
docstring calling it "the reachability probe." It requires a specific
`repo` argument tied to a run, so it cannot check "is this adapter
reachable" independent of any configured repository, and it would fail
misleadingly (a real API error) if the repo argument were coincidentally
right but the token were merely low-privileged for that endpoint. Health
checking needs its own account/identity-shaped probe (e.g. "who am I"),
not a workflow-shaped one.

## R2 — What each adapter's check actually calls

**Decision**: Each adapter's `check_health()` calls the cheapest
authenticated identity/self endpoint the platform exposes, wrapped so any
exception (network, timeout, 401/403, malformed response) is caught and
turned into `False` — never raised.

| Adapter | Call |
|---|---|
| GitHub (`GitHubClient`) | `GET /user` |
| Jira (`JiraClient`) | `GET /myself` |
| GitLab (`GitLabCodeHost`) | `GET /user` |
| Gitea (`GitLabCodeHost`, `is_gitea=True`) | `GET /user` (same client, Gitea implements the same endpoint shape) |
| Fixture (`FixtureTaskSource`) | No call — returns `True` unconditionally (FR-012); it is a local file adapter with nothing external to reach. |

**Rationale**: Every one of these is a single authenticated GET with no
side effects and no dependency on any specific repo/ticket already being
configured — the same shape the requester's own two failing integrations
(Jira, GitLab) already expose for "am I logged in" checks in their own
UIs.

## R3 — Background cadence: a `PollSource`, not a new mechanism

**Decision**: Implement a `HealthPollService` that satisfies the existing
`PollSource` protocol (`backend/app/services/poll_source.py`) — the same
shape `FeedbackPollService`, `JiraPollService`, and the GitHub reconcile
service already use. It is appended to `configured_poll_sources()`,
started/cancelled by the existing lifespan loop in `main.py` (no new
background-task plumbing), and (like `FeedbackPollService`) always
returns `[]` from `list_work_items()` — it has no dry-run ticket listing,
only a recheck cycle.

**Rationale**: `main.py`'s lifespan already owns exactly one place that
creates and cancels every background poll task; reusing it means zero new
startup/shutdown code and zero new failure modes to reason about
(Principle IV — deliberate simplicity).

**Cadence**: A new `health_check_interval_seconds` setting, default `60`
— short enough that SC-001 ("see broken integration within seconds of
loading any page") is normally already true from the *last* automatic
cycle by the time an operator looks, without being so frequent it adds
meaningful load. Deliberately independent from the existing
`poll_interval_seconds` (default `300`, feature/ticket polling) — health
is a much cheaper, much more time-sensitive check than ticket polling.

**Per-check timeout**: A new `health_check_timeout_seconds` setting,
default `10`, wraps each adapter's `check_health()` call in
`asyncio.wait_for(...)`; a timeout is treated identically to any other
failure (unhealthy). This is what satisfies FR-008/SC-005 — one
unresponsive integration cannot stall the others, since each check is
bounded independently and the cycle runs them one after another (not
concurrently — see R6).

## R4 — Delivery to the frontend: push (SSE), not poll

**Decision**: Mirror the existing notification-center pattern exactly
(`backend/app/routers/notifications.py`,
`frontend/src/composables/useNotifications.ts`): a keyless `HealthBus`
(pub/sub tick), a `GET /api/health/events` SSE stream that emits the
current list on connect and again on every change, and a plain
`GET /api/health` for the one-shot fetch. No frontend polling timer is
introduced.

**Rationale**: `useConnectivity.ts`'s own comment states the app
"otherwise has no periodic polling left (push, not poll)" — introducing
a new frontend `setInterval` for this feature would be a regression
against that already-established direction, not a neutral choice.

## R5 — Persistence: none

**Decision**: Health status is held in a plain in-memory store
(`HealthStore`, no Alembic table), reset to "not yet known" on every
process restart.

**Rationale**: Status is a live, continuously-recomputed fact about an
external system's *current* reachability — a value from before restart
is not meaningfully more trustworthy than "unknown," and the background
cycle already re-establishes real status within one cadence interval of
startup (FR-009). This also matches this project's stated design
principle that kestrel carries little to no persistence of its own
derived/transient state.

## R6 — Concurrency and dedup: hand-curated at bootstrap, not inferred

**Decision**: `HealthPollService` is constructed with an explicit,
ordered list of `(label, check_fn)` pairs built directly in
`app/services/workflows/bootstrap.py`, the same place `sources` and
`code_hosts` dicts are already hand-assembled. For a GitHub profile,
only one entry is registered (backed by the shared `GitHubClient`) even
though both `GitHubTaskSource` and `GitHubCodeHost` wrap it and both
implement `check_health()` — bootstrap simply doesn't register the
second one. Checks within one cycle run sequentially, each individually
timeout-bounded (R3); one hanging/failing check delays but never blocks
the others (each still runs, each still bounded).

**Rationale**: FR-010 (no duplicate indicator for one underlying
connection) and the "two distinct profiles of the same adapter type
still get independent entries" edge case are both already fully known
at bootstrap time — bootstrap.py is the one place that knows whether two
adapter instances share a credential/connection or not, since it is what
constructed them. A generic runtime dedup-by-identity algorithm would
solve a problem that does not exist yet (today's bootstrap wiring
supports at most one profile per adapter type) and would need its own
tests and edge cases for no present benefit (Principle IV, YAGNI).

## R7 — Manual refresh and in-flight dedup

**Decision**: `POST /api/health/{name}/refresh` looks up the named
entry, and — guarded by a per-entry `asyncio.Lock` — runs its check
immediately if no check for that entry is currently in flight (the
background cycle's own run for that entry, or a concurrent manual
refresh), otherwise it is a no-op that returns the entry's current
(soon-to-be-updated) state. Either way the bus ticks once the in-flight
check (whichever triggered it) resolves.

**Rationale**: Directly satisfies FR-005 (no duplicate concurrent
checks) with the simplest primitive available (`asyncio.Lock`), reusing
the same background cycle's check function rather than a second
implementation.
