# Feature Specification: Source Health Checks

**Feature Branch**: `014-source-health-checks`

**Created**: 2026-09-08

**Status**: Draft

**Input**: User description: "Source/code-host health checks: surface whether each configured TaskSource and CodeHost adapter (Jira, GitLab, GitHub, Gitea, fixture) is currently reachable and authenticated, so a misconfiguration (network issue or bad credentials) is visible in the UI instead of only surfacing later as a failed run. Health is a new capability on the existing TaskSource/CodeHost ports (not a new port) — the same capability should be planned for the future FeedbackSource port from issue #37 when that's designed. Only a binary healthy/unhealthy indicator is shown in the UI; the underlying technical detail (network vs auth) is not surfaced to the user. Confirmed decisions: checked on a background poll cycle (mirroring the existing PollSource pattern) plus an on-demand manual refresh from the UI; displayed as a persistent per-source indicator in the app's top app bar, visible everywhere in the app, not confined to a settings page."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See integration health at a glance (Priority: P1)

While working anywhere in kestrel, the operator can see, without navigating anywhere, whether each configured integration (a task source like Jira or GitHub, and a code host like GitLab or GitHub) is currently reachable and authenticated. Status is kept fresh automatically by a recurring background check — the operator doesn't have to do anything to see current state.

**Why this priority**: This is the entire point of the feature: today a broken integration is only discovered when a run fails, sometimes long after the misconfiguration was introduced. A persistent, always-visible indicator turns a delayed, indirect failure into an immediate, direct signal — this alone delivers the full value even before any manual-refresh affordance exists.

**Independent Test**: Configure a source with a deliberately broken credential; without triggering any workflow run, confirm the app-bar indicator for that source turns unhealthy on its own within one background check cycle, and stays healthy for every correctly configured source.

**Acceptance Scenarios**:

1. **Given** every configured source is reachable and authenticated, **When** the operator loads any page in the app, **Then** every source shows a healthy indicator.
2. **Given** one configured source has an invalid credential, **When** the background check cycle runs, **Then** that source's indicator (and only that one) shows unhealthy, on every page, without the operator navigating anywhere.
3. **Given** a source's network endpoint is unreachable, **When** the background check cycle runs, **Then** that source shows unhealthy — visually indistinguishable from an authentication failure.
4. **Given** the app has just started and no check has completed yet, **When** the operator loads a page, **Then** the affected source(s) show a neutral "not yet known" state, never a false "healthy".

---

### User Story 2 - Manually refresh a source's health (Priority: P2)

After fixing a misconfiguration (e.g. rotating an expired token), the operator can trigger an immediate recheck of a source instead of waiting for the next background cycle, so they can confirm the fix worked right away.

**Why this priority**: Materially improves the operator's troubleshooting loop, but the feature already delivers its core value through User Story 1's automatic background checks alone — this only removes the wait.

**Independent Test**: With a source currently showing unhealthy, fix its configuration, trigger the manual refresh control, and confirm the indicator updates to healthy immediately, without waiting for the next scheduled cycle.

**Acceptance Scenarios**:

1. **Given** a source shows unhealthy, **When** the operator triggers a manual refresh, **Then** that source is rechecked immediately and its indicator updates to reflect the new result.
2. **Given** a manual refresh is already in flight for a source, **When** the operator triggers another refresh for the same source, **Then** no duplicate concurrent check is started.

### Edge Cases

- No sources are configured beyond the local fixture adapter (a common local-dev setup): the fixture indicator shows healthy without performing any real network I/O, since it has nothing external to reach.
- A source's check hangs (the endpoint accepts the connection but never responds): the check MUST give up after a bounded wait and report unhealthy, rather than leaving the indicator stuck in "checking" indefinitely or blocking other sources' checks.
- The same underlying adapter/credential pair is configured as both the task source and the code host (e.g. GitHub, which conflates both roles) — it is checked once and reflected as one status, not duplicated as two independent indicators for the same failure.
- Two different source profiles happen to point at the same external service — each configured profile still gets its own independent check and indicator, since they may use different credentials.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST determine, for each configured task-source adapter and code-host adapter, whether it is currently reachable and successfully authenticated.
- **FR-002**: The system MUST only ever report one of exactly three states externally — healthy, unhealthy, or not-yet-known — and MUST NOT expose which underlying condition (network failure vs. authentication failure vs. any other cause) produced an unhealthy result.
- **FR-003**: The system MUST re-check every configured source automatically on a recurring schedule, with no operator action required.
- **FR-004**: The operator MUST be able to trigger an immediate re-check of a source on demand, without waiting for the next scheduled cycle.
- **FR-005**: Triggering a manual re-check for a source that already has a check in flight MUST NOT start a second, redundant check for that same source.
- **FR-006**: The UI MUST display a status indicator for every configured source, positioned so it is visible from anywhere in the app, not only from a dedicated settings view.
- **FR-007**: A health check MUST NOT delay, block, or otherwise interfere with any in-progress or newly dispatched workflow run.
- **FR-008**: A single source's health check MUST be bounded in duration, so one unresponsive integration cannot stall the checks for other configured sources.
- **FR-009**: Before a source's first check has completed (e.g. immediately after startup), the system MUST represent it as not-yet-known rather than defaulting to either healthy or unhealthy.
- **FR-010**: Two configured source profiles that share the same underlying adapter instance and credentials (e.g. GitHub acting as both task source and code host for one profile) MUST be represented as a single indicator, not two independent ones reporting the same underlying check.
- **FR-011**: The health-check capability MUST be expressed as part of the existing task-source and code-host integration contracts, so it is implemented uniformly by every adapter (GitHub, Jira, GitLab, Gitea, the local fixture adapter).
- **FR-012**: The local fixture adapter MUST always report healthy without performing any real network call, since it has no external dependency to fail.

### Key Entities

- **Source Health**: The current reachability/authentication status of one configured integration (a task-source adapter or a code-host adapter). Attributes: which configured profile it belongs to, its current state (healthy / unhealthy / not-yet-known), and when it was last checked.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can determine whether any configured integration is currently broken within seconds of loading any page in the app — no navigation to a separate view required.
- **SC-002**: After correcting a misconfigured integration, an operator can confirm the fix is recognized in under 10 seconds using the manual refresh, without restarting the application.
- **SC-003**: Every configured integration is represented by exactly one status indicator — no configured source is ever left unrepresented, and no source is ever represented twice.
- **SC-004**: Background health checks add no perceptible delay to dispatching or running a workflow.
- **SC-005**: An unresponsive integration's check completes (as unhealthy) within a bounded, short amount of time rather than hanging — verified by the check cycle for all other sources completing on schedule regardless of one source's unresponsiveness.

## Assumptions

- "Configured source" means every task-source and code-host adapter instance that is actually set up and reachable via kestrel's existing profile configuration — not every adapter kestrel could theoretically support.
- The background check cadence is a short, fixed interval (on the order of the existing polling cadence already used for ticket/feedback polling elsewhere in the system), not independently configurable per source in this iteration.
- "Reachable and authenticated" is satisfied by the cheapest read-only call each adapter already has available (e.g. an existing "fetch current identity/rate-limit" or equivalent call) — no new write operations are introduced purely for health checking.
- The health indicator is a single always-on-screen element (e.g. in the app's top bar); it does not need its own dedicated settings page in this iteration, though nothing here precludes adding one later.
- This feature does not attempt to distinguish or recover from *why* a source is unhealthy (retry strategies, alerting, auto-remediation) — it only detects and displays current state.
- The future `FeedbackSource` port (tracked in issue #37) is expected to expose the same health-check capability once it is designed; this feature does not implement or block on that port, but its port-contract shape should not preclude it.
