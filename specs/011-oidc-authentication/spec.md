# Feature Specification: OIDC authentication & permission-based authorization

**Feature Branch**: `011-oidc-authentication`

**Created**: 2026-08-31

**Status**: Draft

**Input**: User description: "Add opt-in OIDC authentication and
permission-based authorization to kestrel, gated behind the operator's own
identity provider (Keycloak), so state-mutating actions can be restricted to
signed-in users holding the right role, while remaining fully open when the
feature is left disabled."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator gates kestrel behind sign-in (Priority: P1)

An operator who wants to run kestrel somewhere more exposed than a trusted
loopback connection turns on authentication. Once enabled, anyone reaching
kestrel's web UI or API must sign in with the operator's identity provider
before they can see or use anything. An operator who does not need this
leaves it off and kestrel behaves exactly as it always has.

**Why this priority**: This is the feature's foundation — without a working
opt-in gate, no permission logic can matter, and getting the "disabled means
unchanged" guarantee wrong would break every existing deployment.

**Independent Test**: Can be fully tested by toggling the feature off and
confirming zero behavior change, then toggling it on and confirming an
unauthenticated visitor is required to sign in before reaching any part of
kestrel.

**Acceptance Scenarios**:

1. **Given** the feature is left at its default (disabled) setting, **When**
   anyone opens kestrel's web UI or calls its API, **Then** they see and use
   it exactly as before, with no sign-in prompt anywhere.
2. **Given** the operator has enabled the feature and configured their
   identity provider, **When** an unauthenticated visitor opens kestrel,
   **Then** they are sent to sign in before anything else in kestrel is
   shown.
3. **Given** the operator has enabled the feature, **When** a visitor
   completes sign-in successfully, **Then** they land back in kestrel and can
   see kestrel's normal views.

---

### User Story 2 - Signed-in users are limited to what they're permitted to do (Priority: P2)

Once sign-in is required, the operator wants different signed-in people to
be able to do different things. Someone who should only be able to watch
progress must not be able to trigger destructive actions (like discarding a
run's history and starting it over, or deleting a session); someone the
operator has explicitly trusted with those actions can perform them.

**Why this priority**: This is the actual protection the operator is after —
sign-in alone doesn't prevent damage; restricting *who* can trigger
consequential actions is the point of the feature. It depends on User
Story 1 (sign-in must exist first) but is independently demonstrable once
sign-in works.

**Independent Test**: Can be fully tested by signing in as two different
configured identities — one granted a given permission, one not — and
confirming the corresponding action succeeds for one and is refused for the
other, for every state-mutating action in kestrel.

**Acceptance Scenarios**:

1. **Given** a signed-in user has not been granted permission for a specific
   mutating action (e.g., discarding and restarting a run, or permanently
   deleting a session), **When** they attempt it, **Then** kestrel refuses
   the action and the option is visibly unavailable to them beforehand.
2. **Given** a signed-in user has been granted permission for a specific
   mutating action, **When** they perform it, **Then** kestrel carries it out
   exactly as it does today for any user when the feature is disabled.
3. **Given** a signed-in user has no permissions granted at all, **When**
   they use kestrel, **Then** they can still see kestrel's existing data
   (running sessions, workflow status, history) but cannot trigger any
   mutating action.
4. **Given** kestrel's live-updating views (session progress, workflow
   progress, notifications), **When** a signed-in user is watching one,
   **Then** it continues to update in real time exactly as it does when the
   feature is disabled.

---

### User Story 3 - Operator maps their own roles to kestrel's permissions (Priority: P3)

The operator's identity provider already groups people using its own
role names (some scoped to the whole organization/realm, some scoped
specifically to the kestrel application). The operator wants to decide,
in one place and without touching kestrel's code, which of those role
names grant which kestrel permission — and wants both kinds of role to
be usable, since their identity provider offers both.

**Why this priority**: Valuable and necessary for the feature to be usable
in practice, but it is a configuration/administration concern layered on
top of User Stories 1 and 2 rather than a separate protection in its own
right — the operator could, in principle, ship with a fixed default mapping
and still get value from Stories 1 and 2 alone.

**Independent Test**: Can be fully tested by changing only the operator's
role-to-permission configuration (no code change) and confirming a signed-in
user's allowed actions change accordingly on the next restart, for a role
defined at either the organization-wide level or the kestrel-application
level.

**Acceptance Scenarios**:

1. **Given** the operator's identity provider reports an organization-wide
   role for a signed-in user, **When** the operator has mapped that role
   name to a kestrel permission, **Then** the user is granted that
   permission.
2. **Given** the operator's identity provider reports a kestrel-specific
   role for a signed-in user, **When** the operator has mapped that role
   name to a kestrel permission, **Then** the user is granted that
   permission, exactly as with an organization-wide role.
3. **Given** the operator changes which role maps to which permission,
   **When** kestrel is restarted, **Then** signed-in users' allowed actions
   reflect the new mapping.

---

### Edge Cases

- A signed-in user has no role-to-permission mapping that applies to them at
  all: they remain able to view kestrel (User Story 2, scenario 3) — this is
  a normal, expected state, not an error.
- kestrel cannot verify a request's identity (an invalid, expired, or
  otherwise unverifiable credential): access is refused (fails closed), not
  silently granted.
- Re-authentication after an expired sign-in resolves the problem on its own
  (the common case) and the user continues where they left off; if
  re-authenticating again would not change the outcome (e.g. the operator's
  identity-provider configuration itself is mismatched), the user sees a
  clear, actionable message instead of being sent to sign in over and over.
- The operator turns the feature off after it has been in use: kestrel
  reverts to being fully open, exactly as in the disabled default.
- Task ingestion (kestrel noticing new work from an external ticket source
  such as GitHub or Jira) is unaffected by this feature either way — who may
  create a task in that external system remains that system's own
  responsibility, not something kestrel evaluates.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a single operator-controlled setting
  that turns authentication on or off, defaulting to off.
- **FR-002**: When the setting is off, the system MUST behave identically to
  its current unauthenticated behavior — no sign-in prompt, no restricted
  actions, on any existing entry point.
- **FR-003**: When the setting is on, the system MUST require every visitor
  to sign in through the operator's configured identity provider before
  reaching any part of kestrel.
- **FR-004**: The system MUST recognize roles the identity provider reports
  at both the organization-wide (realm) level and the application-specific
  (client) level for a signed-in user.
- **FR-005**: The system MUST let the operator define, through configuration
  and without modifying kestrel's code, which identity-provider role names
  grant which of kestrel's own permissions.
- **FR-006**: The system MUST define its own fixed set of permissions,
  independent of any identity provider's role-naming scheme, and application
  behavior MUST be gated only on those permissions.
- **FR-007**: When authentication is on, the system MUST require the
  matching permission before allowing any of the following actions: starting
  or resuming a session; deleting a session; approving, rejecting, or
  responding to a workflow gate; cleaning up a workflow; rerunning a
  workflow; deleting a workflow.
- **FR-008**: A signed-in user who has not been granted a given permission
  MUST be prevented from performing the corresponding action, and MUST be
  shown, before attempting it, that the action is unavailable to them.
- **FR-009**: A signed-in user without any granted permission MUST still be
  able to view kestrel's existing read-only data (session and workflow
  status and history).
- **FR-010**: kestrel's live-updating views MUST continue to update for a
  signed-in user with no perceptible difference from their behavior when
  authentication is disabled.
- **FR-011**: The system MUST NOT be the sole enforcer of a permission in
  its own display layer — any visual indication of what a user may or may
  not do MUST be backed by the same restriction being enforced wherever the
  action is actually carried out.
- **FR-012**: The system's identity-provider integration MUST be designed so
  that supporting an additional identity provider in the future does not
  require redesigning the permission model — only adding support for that
  provider's own way of reporting roles.
- **FR-013**: Enabling authentication MUST NOT introduce per-user ownership
  of any existing kestrel data (sessions, workflows, or anything else) —
  kestrel remains one shared workspace regardless of how many distinct
  identities can sign in.
- **FR-014**: The system MUST NOT evaluate or enforce who may create or
  update a task in an external ticket source (e.g. GitHub, Jira); this
  MUST be documented as the responsibility of that external source's own
  access control, out of scope for kestrel.
- **FR-015**: When a signed-in user's credential can no longer be verified,
  the system MUST attempt at most one automatic re-authentication before
  presenting a clear, actionable error rather than repeating the attempt
  indefinitely.

### Key Entities

- **Authenticated Identity**: The signed-in visitor's identity as asserted
  by the operator's identity provider for the current request — a subject
  identifier, a display name/email, and the roles that provider currently
  reports for them. Not stored by kestrel beyond the current request.
- **Permission**: One of kestrel's own, fixed set of named capabilities,
  each gating exactly one consequential action (e.g. "delete a session",
  "clean up a workflow"). Defined by kestrel, never by the identity
  provider.
- **Role Mapping**: An operator-authored association between one
  identity-provider role name (organization-wide or application-specific)
  and the set of kestrel permissions that role grants.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With authentication left at its default (disabled), 100% of
  kestrel's existing usage flows are unchanged — no regression is
  observable by an operator who does not opt in.
- **SC-002**: An operator can require sign-in and decide which signed-in
  identities may perform which mutating actions using configuration alone,
  without modifying kestrel's code.
- **SC-003**: For every state-mutating action kestrel offers, a signed-in
  user without the matching permission is refused it, and a signed-in user
  with the matching permission can perform it, with no exceptions.
- **SC-004**: Signed-in users experience kestrel's real-time updates
  (session progress, workflow progress, notifications) with no perceptible
  difference from the disabled-authentication experience.
- **SC-005**: A user whose credential fails verification is never caught in
  a repeating sign-in loop — they either recover automatically within one
  attempt or see a clear explanation of what went wrong.

## Assumptions

- The operator already runs, or will run, a standards-compliant OpenID
  Connect identity provider (Keycloak, initially) capable of reporting both
  organization-wide and application-specific roles for a signed-in user.
- Turning authentication on or off, and changing the role-to-permission
  mapping, are deliberate operator actions applied at kestrel's startup, not
  something toggled per request or live without a restart.
- "Permission" is a vocabulary kestrel itself defines; kestrel does not
  attempt to infer meaning from arbitrary or free-form identity-provider
  role names beyond what the operator explicitly maps.
- A signed-in user with no permissions mapped to any of their roles is a
  valid, expected, view-only state, not an error condition.
- Task-ingestion-level access control (who may create or update a ticket in
  an external tracker) remains entirely the responsibility of that external
  system; this feature does not add any enforcement of it within kestrel.
- Kestrel remains a single shared workspace: enabling authentication changes
  *who may act*, not *what data belongs to whom* — no per-user data
  ownership is introduced.
