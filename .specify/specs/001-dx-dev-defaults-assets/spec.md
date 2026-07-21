# Feature Specification: DX polish — zero-config dev servers & lighter frontend assets

**Feature Branch**: `dev/sane-dev-workflow`

**Created**: 2026-07-21

**Status**: Draft

**Input**: User description: "DX / demo polish: dev-server defaults + bundle size — bake sane dev-server defaults so `npm run dev` / `uv run uvicorn` just work, align the frontend API base default with the local backend port, and reduce first-load frontend weight (currently the full Material Design Icons webfont ships even though only a handful of glyphs are used)."

## Overview

Two developer-experience papercuts, both surfaced while running the app from
source and during the deep-Vuetify-adoption work:

1. **Starting the dev servers takes more ceremony than it should.** A
   contributor should be able to clone the repo and run the backend and
   frontend dev servers with no environment variables, and have the UI talk to
   the backend immediately.
2. **The first page load ships more than it needs to.** The complete Material
   Design Icons webfont (and its inflated stylesheet) is downloaded even though
   only a small set of icons is ever displayed, and all view code loads up
   front regardless of which view the user opens first.

This spec is scoped to the developer/first-load experience. It does not add
product features and does not change what the application does once running.

## Clarifications

### Session 2026-07-21

- Q: The backlog names backend port **8001** as the new default, but the entire
  repo (README, `docs/`, docker, getting-started) currently standardises on
  **8000**, and the frontend API base already defaults to `:8000`. Which port
  is canonical? → **A: 8000.** Align to the existing standard; the backlog's
  "8001" is not adopted. The frontend default already matches, so no port
  mismatch exists to fix.
- Q: The backlog asks for a **committed** `frontend/.env`, but the constitution
  requires `.env` to stay out of version control (`.env.example` is the source
  of truth). How should the zero-config default be delivered? → **A: In-code
  default plus a documented `.env.example` entry.** No real `.env` is committed;
  the constitution is honoured.
- Q: Is panel code-splitting (User Story 3) in scope for this feature, or
  deferred? → **A: In scope but optional/best-effort.** The icon-payload
  reduction (US2) is the hard requirement; code-splitting stays a MAY, and its
  measurable outcome (SC-006) is a target, not a completion gate.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run the app from source with zero configuration (Priority: P1)

A contributor clones the repository, installs dependencies, and starts the
backend and frontend dev servers using the documented one-liners. Without
setting any environment variables, the frontend loads and successfully
exchanges data with the backend on the first try.

**Why this priority**: This is the first thing every contributor (and the
author, on a fresh machine) does. Friction here blocks all other work and
makes demos fragile. It is the highest-leverage papercut to remove.

**Independent Test**: On a clean checkout with no environment variables set,
start both dev servers and load the UI in a browser; confirm the sessions and
workflows views populate from the backend without a configuration step and
without console/network errors caused by a wrong API base URL.

**Acceptance Scenarios**:

1. **Given** a fresh checkout with no `.env`/`.env.local` and no exported
   environment variables, **When** the developer starts the backend dev server
   with the documented command, **Then** it listens on the project's canonical
   dev port with no extra flags required.
2. **Given** the backend running on its canonical dev port, **When** the
   developer starts the frontend dev server with the documented command and
   opens the UI, **Then** the frontend issues API requests to that same port
   and the views populate successfully.
3. **Given** the documented dev workflow, **When** a contributor follows the
   getting-started / development docs verbatim, **Then** every port and URL the
   docs mention is mutually consistent (no doc says one port while the code
   defaults to another).

---

### User Story 2 - Only ship the icons that are actually used (Priority: P2)

When the UI first loads, only the icon glyphs the application actually renders
are downloaded, instead of the entire Material Design Icons set. This
noticeably reduces the first-load transfer size and the amount of styling the
browser must parse.

**Why this priority**: This is the single largest avoidable item in the
first-load payload today (a ~400 kB icon webfont plus a heavily inflated
stylesheet). It directly improves first paint and demo responsiveness, and it
is self-contained.

**Independent Test**: Build the frontend for production and inspect the emitted
assets; confirm no full icon webfont is present, that total first-load asset
weight (scripts + styles + fonts) is materially smaller than before, and that
every icon visible in the UI still renders correctly in both light and dark
themes.

**Acceptance Scenarios**:

1. **Given** a production build, **When** the emitted assets are inspected,
   **Then** the complete icon webfont is no longer among them and only the
   referenced glyphs contribute to the shipped payload.
2. **Given** the running UI, **When** a user navigates every view, **Then**
   every icon that rendered before still renders, with no missing-glyph
   placeholders, in both light and dark themes.

---

### User Story 3 - Load view code on demand (Priority: P3)

The code for a given view is fetched only when that view is first opened, so the
initial download for the default view is smaller and first paint is faster. The
non-default view loads on demand without a jarring gap.

**Why this priority**: A further first-load win, but smaller than the icon
payload and only worthwhile once US2 is in place. Lower risk to defer.

**Independent Test**: Build for production and load the default view; confirm
the initial download does not include the other view's code, and that switching
to the other view fetches it on demand and renders correctly with an
appropriate loading affordance.

**Acceptance Scenarios**:

1. **Given** a production build, **When** the default view loads, **Then** the
   code unique to the other view is not part of the initial download.
2. **Given** the default view is open, **When** the user switches to the other
   view for the first time, **Then** that view's code is fetched on demand and
   the view renders, with a loading indicator shown if the fetch is not
   instantaneous.

---

### Edge Cases

- **Explicit override still wins**: If a developer *does* set the API base
  (e.g. to point the frontend at a backend on a non-default port or host), the
  explicit value must take precedence over the baked-in default.
- **Packaged image unaffected**: In the bundled Docker image the backend serves
  the built SPA same-origin. The dev default must not force a cross-origin base
  URL into the packaged build or otherwise break same-origin serving.
- **Both run modes keep working**: The constitution requires both the bundled
  Docker image and the run-from-source dev flow to remain functional; neither
  the default nor the asset changes may break either.
- **On-demand view fetch fails**: If loading a view's code on demand fails
  (offline, transient error), the user sees a clear error rather than a blank
  view or a silent failure.
- **Icon referenced dynamically**: If an icon name is chosen at runtime rather
  than written as a literal, it must still resolve — the set of shipped glyphs
  must cover every icon the UI can display.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The backend dev server MUST start on a single canonical dev port
  using the documented command with no extra flags or environment variables.
- **FR-002**: The canonical dev port MUST be **8000**, consistent across the
  backend default, the frontend's default API base, and all developer-facing
  documentation. (Decision: align to the existing repo standard; the backlog's
  "8001" is not adopted.)
- **FR-003**: With no developer-provided configuration, the frontend MUST
  default its API base to `http://localhost:8000` so a fresh checkout works out
  of the box. This default MUST be delivered via the in-code fallback (already
  present) with the override documented in `frontend/.env.example`; a real
  `.env` MUST NOT be committed (constitution constraint).
- **FR-004**: A developer-provided API base value (via the supported
  configuration mechanism) MUST override the baked-in default.
- **FR-005**: Other dev-time settings needed to run from source (e.g. the
  workspace root) MUST have working defaults so no environment variables are
  required for a basic run-from-source session.
- **FR-006**: The production build MUST NOT ship the complete icon webfont; only
  icon glyphs actually referenced by the UI may contribute to the shipped
  payload.
- **FR-007**: Every icon visible in the UI before this change MUST still render
  after it, in both light and dark themes, with no missing-glyph placeholders.
- **FR-008**: The production build MUST complete without warnings about
  oversized assets or chunks under the project's configured size budget.
- **FR-009**: View-specific code MAY be loaded on demand (optional/best-effort;
  not a completion gate) so that the initial download for the default view
  excludes code unique to other views. *If* implemented, the UI MUST show a
  loading affordance when the on-demand fetch is not immediate and MUST surface
  a clear error if it fails. The icon-payload reduction (FR-006/FR-007) is the
  hard first-load requirement; code-splitting is an additive optimisation.
- **FR-010**: All developer-facing documentation touched by the port/default
  changes MUST be updated in the same change so docs and behaviour stay
  consistent (constitution: docs kept consistent with behaviour).
- **FR-011**: Any dependency added or removed to achieve the icon-payload
  reduction MUST be justified per the constitution's dependency rule, and both
  the bundled-image and run-from-source modes MUST remain working.

### Non-Functional / Constraints

- **NFR-001**: Changes MUST respect the constitution: `.env` stays out of
  version control, new dependencies are justified, and both run modes keep
  working.
- **NFR-002**: This feature MUST NOT change application behaviour beyond
  developer setup and asset delivery (no new product capabilities, no API
  contract changes).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a clean checkout, a developer can bring up both dev servers and
  see the UI populate from the backend with **zero** environment variables set
  and **zero** manual configuration steps.
- **SC-002**: Following the getting-started/development docs verbatim yields a
  working setup on the first attempt, with every port/URL reference mutually
  consistent (no contradictory port numbers between docs and defaults).
- **SC-003**: First-load asset payload (scripts + styles + fonts, uncompressed)
  is reduced by at least 50% relative to the current build, driven primarily by
  eliminating the full icon webfont.
- **SC-004**: A production build emits no oversized-asset/chunk warnings.
- **SC-005**: 100% of icons that rendered before the change still render after
  it, verified across every view in both light and dark themes.
- **SC-006** *(target, not a completion gate — US3 is optional/best-effort)*:
  If code-splitting is implemented, the initial download for the default view
  does not include code unique to the non-default view (verified in the emitted
  build assets). If US3 is not implemented, this criterion does not block
  completion.

## Assumptions

- The "users" of this feature are contributors/operators running kestrel from
  source; there is no separate end-user-facing behaviour change.
- The canonical dev port is **8000** (the value already used throughout the
  repo); the backlog's "8001" is not adopted (resolved, FR-002).
- The zero-config API-base default is delivered via the in-code fallback plus a
  documented `.env.example` entry, without committing a real `.env`, honouring
  the constitution (resolved, FR-003).
- Only a small, enumerable set of icon glyphs is used, making an
  only-referenced-icons approach viable without visual regressions.
- The frontend currently exposes exactly two primary views (workflows and
  sessions) that are candidates for on-demand loading.
- Success criterion SC-003's baseline is the current production build measured
  during the Vuetify-adoption work (~458 kB JS, CSS ~649 kB, ~403 kB icon
  webfont); the actual reduction will be re-measured against the build at
  implementation time.

## Dependencies

- Existing frontend build tooling and the existing component library's icon
  configuration.
- Developer-facing docs (getting-started, development, troubleshooting) that
  reference the dev port and setup steps and must be kept consistent.
- The constitution's binding constraints on secrets, dependencies, and dual run
  modes.
