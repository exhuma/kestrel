# Feature Specification: Task-source configuration abstraction & poll tooling

**Feature Branch**: `004-task-source-config`

**Created**: 2026-07-23

**Status**: Draft

**Input**: User description: "Replace the source-specific, partly-redundant
ingestion config with one abstract task-source list; unify the poll cadence;
detect a Jira RFC's target repo from web/remote links as well as a custom
field; and add a command to dry-run the poll across all configured sources."

## Context & Motivation

Kestrel ingests work from external task sources (GitHub issues today, Jira RFCs
added in feature 003, with GitLab/Planka planned). Each source was bolted on
with its own scalar configuration keys, which has produced three operator-facing
problems:

- **Divergent, redundant config.** GitHub is selected by a watched-repo
  allow-list plus a trigger label; Jira is selected by a project key plus an
  optional JQL filter — two unrelated vocabularies for the same idea ("which
  items in this source should kestrel act on"), and the Jira project key merely
  duplicates something the JQL can already express.
- **Two interval knobs that mean the same thing.** The GitHub reconcile cadence
  and the Jira poll cadence are configured separately though they play the same
  role (how often kestrel re-checks a source).
- **No way to test a source's configuration** short of running the whole
  service and watching logs, and a Jira RFC's target repository can only be
  named one way (a custom field), which does not match how some teams record it.

This feature is the planned "extract the abstraction when the second source
lands" step (see the multi-source ingestion strategy): with two concrete
sources now in hand, the shared shape is extracted into one consistent
configuration model that future sources slot into.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Configure every task source the same way (Priority: P1)

As the operator, I declare each place kestrel pulls work from as one entry in a
single list, where every entry states its source type and the criteria that
select which items kestrel should act on — regardless of whether the source is
GitHub, Jira, or a future one. Secrets (tokens) are never written into this
list; they stay in the environment and each entry names the environment variable
that holds its token.

**Why this priority**: This is the foundation. It removes the redundant,
divergent per-source keys, gives new sources a place to slot in, and is the
model the other stories build on. Without it, the rest cannot be expressed
consistently.

**Independent Test**: Configure a GitHub entry (repo allow-list + trigger
label) and a Jira entry (instance + selection query + repo resolution) in the
one list, start kestrel, and confirm both sources are recognised and enabled
exactly as before, with no source-specific scalar keys present.

**Acceptance Scenarios**:

1. **Given** a configuration listing one GitHub source and one Jira source,
   **When** kestrel starts, **Then** both the GitHub reconcile loop and the Jira
   poll loop are enabled, and each uses its own entry's selection criteria.
2. **Given** a configuration with no task sources, **When** kestrel starts,
   **Then** no ingestion loop runs and the service starts normally.
3. **Given** a Jira source entry whose token is provided via the named
   environment variable, **When** kestrel starts, **Then** the token is resolved
   from the environment and never required to appear in the configuration file.
4. **Given** a legacy configuration that still uses the old scalar keys,
   **When** kestrel starts, **Then** those keys are ignored (they are no longer
   recognised) so ingestion is governed solely by the task-source list. *(This
   is an accepted breaking change.)*

---

### User Story 2 - Dry-run the poll to verify a source's configuration (Priority: P2)

As the operator, I run a single command that executes each configured source's
selection query and lists the work items it matches — their identifier, title,
and the code repository each resolves to — **without starting any runs**. I use
this to confirm a new or changed source configuration selects what I expect
before letting kestrel act on it.

**Why this priority**: This is the fastest way to validate configuration and was
the immediate pain point (a misconfigured source silently does nothing). It
depends on the sources being enumerable (US1) but delivers standalone value.

**Independent Test**: With one or more sources configured, run the command and
confirm it prints the matching items for every configured source and that no run
is created as a result.

**Acceptance Scenarios**:

1. **Given** a GitHub source and a Jira source are configured, **When** the
   operator runs the poll command, **Then** the matching work items from **both**
   sources are listed, each showing its identifier, title, and resolved code
   repository.
2. **Given** a Jira RFC that matches the query but whose target repository
   cannot be resolved, **When** the operator runs the poll command, **Then** the
   item is still listed and clearly marked as having an unresolved repository.
3. **Given** any configured source, **When** the operator runs the poll command,
   **Then** no new run is started and no comment or other side effect is written
   back to the source.
4. **Given** no sources are configured, **When** the operator runs the poll
   command, **Then** it reports that nothing is configured and exits without
   error.

---

### User Story 3 - Resolve a Jira RFC's repository from a web link (Priority: P3)

As the operator, I can point a Jira RFC at its target code repository either
through a designated custom field (as today) **or** by adding a web/remote link
on the issue whose link text matches a configured label (default "Repository").
Kestrel resolves the repository from the link's URL when the field is absent, so
the custom field is no longer mandatory.

**Why this priority**: It broadens how the target repo can be expressed to match
real team practice, but the existing custom-field path already works, so this is
an enhancement rather than a blocker.

**Independent Test**: Configure a Jira source with no repository custom field,
add a "Repository" web link to an RFC, and confirm kestrel resolves the correct
`owner/name` repository from the link during a dry-run poll.

**Acceptance Scenarios**:

1. **Given** an RFC with the configured repository custom field set, **When**
   kestrel resolves its repository, **Then** the field value is used (unchanged
   behaviour).
2. **Given** an RFC with no repository field but a web link labelled
   "Repository" pointing at a hosted repository URL, **When** kestrel resolves
   its repository, **Then** the `owner/name` repository is parsed from the link
   URL.
3. **Given** an RFC with neither the field nor a matching web link, **When**
   kestrel resolves its repository, **Then** resolution fails cleanly and the RFC
   is reported as having an unresolved repository (no run is started).
4. **Given** a web link whose label does not match the configured link text,
   **When** kestrel resolves the repository, **Then** that link is ignored.

---

### User Story 4 - One cadence for re-checking sources (Priority: P3)

As the operator, I set a single interval that governs how often kestrel
re-checks its task sources, instead of configuring the GitHub reconcile cadence
and the Jira poll cadence separately.

**Why this priority**: A convenience/clarity improvement that removes duplicate
knobs; low risk and low effort, but not required for the abstraction to work.

**Independent Test**: Set the single interval, start kestrel, and confirm both
the GitHub reconcile loop and the Jira poll loop re-check on that interval.

**Acceptance Scenarios**:

1. **Given** the single re-check interval is set, **When** kestrel runs, **Then**
   both the GitHub reconcile loop and the Jira poll loop use it.
2. **Given** a legacy configuration setting one of the old per-source interval
   keys, **When** kestrel starts, **Then** that key is ignored and the single
   interval (or its default) governs both loops. *(Accepted breaking change.)*

---

### Edge Cases

- A task-source entry with an unknown or missing `type` MUST fail configuration
  loading loudly at startup rather than being silently skipped.
- Two entries of the same type (e.g. two Jira instances) are permitted; each is
  evaluated independently and its items are listed/ingested independently.
- A source whose token environment variable is unset SHOULD surface a clear
  startup warning (the source cannot authenticate) rather than failing silently
  at poll time.
- A Jira selection query that returns more items than a single response page MUST
  still be fully enumerated for both ingestion and the dry-run listing.
- A web link URL that is not a recognisable `owner/name` repository URL MUST be
  treated as unresolved, not a malformed crash.
- The dry-run poll command MUST NOT start runs, post comments, or write
  attachments for any source.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST configure all task sources through a single
  ordered list, where each entry declares a source `type` and the selection
  criteria for that type.
- **FR-002**: A GitHub task-source entry MUST carry its own repository
  allow-list and trigger label; a Jira task-source entry MUST carry its own
  instance location, authentication mode/identity, a single selection query, a
  source key (the issue-key prefix, see FR-007a), and its repository-resolution
  settings.
- **FR-003**: The Jira selection MUST be expressed as one whole query written by
  the operator (folding the former separate project key and filter into that one
  query); the system MUST NOT require a separate project field.
- **FR-004**: Secrets (source tokens) MUST NOT be stored in the configuration
  file; each source entry MUST name the environment variable that supplies its
  token, and the system MUST resolve the token from the environment.
- **FR-005**: The task-source list MUST be sourced only from the configuration
  file (not the environment), consistent with how backend routing is configured.
- **FR-006**: The former per-source scalar keys (GitHub watched repos & trigger
  label; Jira project, filter, instance, auth, repo field) MUST be removed and
  no longer honoured. This is an accepted breaking change with no back-compat
  shim.
- **FR-007**: All existing consumers of the removed keys (webhook acceptance,
  GitHub reconcile, Jira poll, the run-to-source/code-host routing, and the
  startup enablement gates) MUST be driven by the task-source list instead, with
  no change to their observable ingestion behaviour.
- **FR-007a**: The dismissal / re-trigger gesture MUST remain scoped per source
  after the removal of the Jira project key. Each Jira entry MUST carry a source
  key (the issue-key prefix, e.g. "RFC") used solely to identify which dismissed
  items belong to that source; clearing a dismissal for one source MUST NOT
  affect another source's dismissed items.
- **FR-008**: The GitHub reconcile cadence and the Jira poll cadence MUST be
  governed by one unified re-check interval with a sensible default; the two
  former per-source interval keys MUST be removed and no longer honoured
  (accepted breaking change).
- **FR-009**: The system MUST provide a command that, for every configured task
  source, executes the source's selection query and lists each matching work
  item's identifier, title, and resolved code repository.
- **FR-010**: The poll command MUST NOT create runs or produce any write-back
  side effect on any source; it is read-only.
- **FR-011**: The poll command MUST cover all configured sources in one
  invocation and MUST report clearly when no sources are configured.
- **FR-012**: The listing capability MUST reuse each source's existing selection
  query logic (the same query used for ingestion), so the dry-run and the live
  poll cannot diverge.
- **FR-013**: A Jira RFC's target repository MUST be resolvable from a designated
  custom field (existing behaviour) or, when that field is absent, from a
  web/remote link on the issue whose link text matches a configured label
  (default "Repository").
- **FR-014**: When resolving from a web link, the system MUST parse the
  `owner/name` repository from the link URL for common hosted-repository URL
  shapes (e.g. a GitHub project URL and a GitLab group/subgroup project URL).
- **FR-015**: The Jira repository custom field MUST become optional; an RFC that
  resolves via a web link and no field MUST ingest identically to one resolved
  via the field.
- **FR-016**: When a task source is misconfigured (unknown type, missing
  required selection criteria), the system MUST fail or warn at startup in a way
  the operator can see, never silently ingest nothing.
- **FR-017**: Documentation and the example configuration files MUST be updated
  to describe the task-source list, the unified interval, the web-link repo
  resolution, and the poll command, and MUST stop referencing the removed keys.

### Key Entities

- **Task source**: A configured origin of work items, identified by a type
  (github, jira, …) and carrying the selection criteria that decide which of its
  items kestrel should act on, plus a reference to the environment variable
  holding its token. Future source types are additional entries of the same
  shape.
- **Work item (dry-run listing)**: A transient view of one matched item produced
  by the poll command — its source, its source-native identifier, its title, and
  the code repository it resolves to (or an indication that the repository is
  unresolved). It represents nothing persisted and starts no run.
- **Repository reference**: The `owner/name` (and optional base branch) target a
  Jira RFC points at, resolved from either the custom field or a matching web
  link.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can configure both a GitHub and a Jira source using a
  single, uniform list structure, with zero source-specific scalar keys
  remaining in their configuration.
- **SC-002**: Adding a new configured source of an existing type requires only
  one additional list entry and no change to existing entries.
- **SC-003**: An operator can verify what each configured source currently
  matches in one command, and running it never creates a run or writes back to
  any source (0 side effects).
- **SC-004**: A Jira RFC can be pointed at its repository with no custom field
  configured, using only a web link, and it ingests identically to the
  field-based path.
- **SC-005**: There is exactly one interval setting governing how often sources
  are re-checked (down from two).
- **SC-006**: Ingestion behaviour observable to the operator (which items start
  runs, dedup, dismissal handling) is unchanged by the configuration
  restructure — the existing behaviour tests still pass.

## Assumptions

- **Extraction now is the planned step, not speculative generality.** The
  single-user/YAGNI principle is honoured because two concrete sources already
  exist; this feature extracts their shared shape rather than inventing an
  abstraction for a hypothetical one.
- **Breaking change is acceptable.** This is a single-user personal tool; the
  maintainer accepts removing the old scalar keys with no migration shim, and
  will update their own configuration file.
- **Secrets stay in the environment.** Reusing the existing "name an environment
  variable that holds the secret" pattern (as backend entries already do) keeps
  the configuration file secret-free.
- **Jira client transport is already migrated** (feature 003 / change set A):
  the enhanced search endpoint and its full-result pagination are in place, so
  full enumeration for both ingestion and the dry-run listing is available.
- **Code host resolution is unchanged**: how a resolved `owner/name` maps to a
  clone/PR host (GitHub/GitLab/Gitea) keeps its current behaviour; only how the
  repository *reference* is discovered from a Jira RFC is broadened.
- **Web-link resolution targets common hosted URL shapes**: GitHub project URLs
  and GitLab group/subgroup project URLs are covered; exotic or self-hosted URL
  layouts that do not follow an `owner/name` path are treated as unresolved
  rather than guessed.
- **The poll command is an operator CLI**, consistent with the existing
  `python -m app` entrypoint; it is not a network endpoint (the loopback/access
  model is unaffected).
