---
description: "Task list for DX polish — zero-config dev servers & lighter frontend assets"
---

# Tasks: DX polish — zero-config dev servers & lighter frontend assets

**Input**: Design documents from `/.specify/specs/001-dx-dev-defaults-assets/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/, quickstart.md

**Tests**: INCLUDED. The constitution's Principle III (Test-First, NON-NEGOTIABLE) and plan.md require vitest coverage for (a) `API_BASE` default resolution and (b) an icon-alias completeness guard. Backend is untouched, so no new backend tests beyond confirming nothing broke.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths are included in each description

## Path Conventions

Web application: `backend/` + `frontend/` at repository root. All changes in this feature are under `frontend/` plus a developer-docs consistency pass; the backend is confirmed unchanged.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the measurement baseline so the US2 payload-reduction claim (SC-003) can be verified against real numbers.

- [X] T001 [P] Capture the pre-change production build baseline: run `cd frontend && npm run build`, then record emitted JS/CSS sizes and the MDI `.woff2` size (per research.md baseline: JS ~458 kB, CSS ~649 kB, woff2 ~403 kB) into a scratch note for the SC-003 before/after comparison in `frontend/` (do not commit build output).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Cross-cutting prerequisites that must exist before user-story work.

**⚠️ Note**: For this feature the three user stories are mutually independent (US1 = dev/env + docs; US2 = frontend icon delivery; US3 = optional code-split). There is **no shared blocking foundation** to build — no database, routing, or base entities. This phase is intentionally empty; user-story phases may begin immediately after Setup.

**Checkpoint**: Proceed directly to user stories.

---

## Phase 3: User Story 1 - Run the app from source with zero configuration (Priority: P1) 🎯 MVP

**Goal**: A fresh checkout brings up both dev servers with zero environment variables and the UI reaches the backend on the first try; all docs agree on port 8000.

**Independent Test**: On a clean checkout with no `.env`/`.env.local` and no exported env vars, start `uv run uvicorn app.main:app --reload` (:8000) and `npm run dev` (:5173); confirm the Workflows and Sessions views populate from `:8000` with no API-base errors, and that copying `.env.example` does not break dev.

### Tests for User Story 1 ⚠️

> Write these tests FIRST and ensure they FAIL before implementation.

- [X] T002 [P] [US1] Add/extend `API_BASE` default-resolution test in `frontend/tests/api/index.spec.ts`: assert unset `VITE_API_BASE` → `http://localhost:8000`, empty string → `''` (same-origin, packaged-image contract preserved), and an explicit value → that value (FR-003/FR-004; research.md R2 three-way semantics).

### Implementation for User Story 1

- [X] T003 [US1] De-footgun `frontend/.env.example`: comment out the `VITE_API_BASE=` line to `# VITE_API_BASE=` so copying the example leaves the var unset and dev falls through to the `:8000` default (research.md R2; FR-003).
- [X] T004 [US1] Verify (and adjust only if wrong) the `API_BASE` fallback in `frontend/src/api/index.ts` (`import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'`); keep the `??` empty-string semantics unchanged so the packaged image's `empty = same-origin` contract holds (FR-004; edge case: packaged image unaffected).
- [X] T005 [P] [US1] Docs consistency pass for the canonical port: run `grep -rn 8001` across `README.md`, `docs/`, and `backend/README.md`; confirm every port/URL reference is `8000` and fix any stragglers so docs and defaults agree (FR-002/FR-010; SC-002).
- [X] T006 [US1] Confirm backend zero-config run-from-source: verify `uv run uvicorn app.main:app --reload` defaults to `:8000` and that `workspace_root` in `backend/app` settings defaults to `./.kestrel-workspaces` so no env vars are required for a basic session (FR-001/FR-005; no code change expected — record the confirmation).

**Checkpoint**: US1 is independently testable — zero-config dev works, the `.env.example` copy does not break it, explicit override wins, and all docs say 8000. This is the MVP.

---

## Phase 4: User Story 2 - Only ship the icons that are actually used (Priority: P2)

**Goal**: Replace the full `@mdi/font` webfont with Vuetify's `mdi-svg` iconset backed by tree-shaken `@mdi/js`, so only the 13 referenced glyphs ship; every icon still renders in both themes and the build emits no oversized-asset warning.

**Independent Test**: Run `npm run build`; confirm no MDI webfont among emitted assets, no size warning, ≥50% uncompressed first-load reduction vs. the T001 baseline, and (via `npm run dev`) that all 13 icons render with no missing-glyph boxes in light and dark themes.

### Dependency swap (US2 prerequisite)

- [X] T007 [US2] Update `frontend/package.json`: add `@mdi/js`, remove `@mdi/font`, then run `cd frontend && npm install` to update the lockfile (Principle IV: net dependency count unchanged; research.md R1).

### Tests for User Story 2 ⚠️

> Write this test FIRST and ensure it FAILS before implementation.

- [X] T008 [P] [US2] Create `frontend/tests/plugins/icons.spec.ts`: grep `frontend/src/**` for `mdi-[a-z-]+` usages, map each to its alias, and assert every one resolves to a non-empty SVG path in the alias registry — a completeness guard preventing missing-glyph regressions (data-model.md validation rule; FR-007; SC-005).

### Implementation for User Story 2

- [X] T009 [US2] Create `frontend/src/plugins/icons.ts` exporting the 13-entry alias registry (`Record<string,string>`) mapping alias names to tree-shaken `@mdi/js` exports per data-model.md (alertCircle→mdiAlertCircle, arrowRight, bell, circle, circleOutline, close, codeJson, cogOutline, radar, rocketLaunchOutline, subdirectoryArrowRight, weatherNight, weatherSunny).
- [X] T010 [US2] Update `frontend/src/main.ts`: remove `import '@mdi/font/css/materialdesignicons.css'`; configure Vuetify `icons: { defaultSet: 'mdi', aliases, sets: { mdi } }` where `mdi` comes from `vuetify/lib/iconsets/mdi-svg` and `aliases` from `plugins/icons.ts` (research.md R1 migration mechanics). Depends on T009.
- [X] T011 [P] [US2] Update icon references in `frontend/src/App.vue` from `mdi-*` to the `$alias` form (`mdi-circle`, `mdi-circle-outline`, `mdi-weather-night`, `mdi-weather-sunny`). Depends on T009, T010.
- [X] T012 [P] [US2] Update icon references in `frontend/src/components/NotificationCenter.vue` to `$alias` form (`mdi-bell`, `mdi-circle`, `mdi-circle-outline`). Depends on T009, T010.
- [X] T013 [P] [US2] Update icon references in `frontend/src/components/WorkflowPanel.vue` to `$alias` form (`mdi-alert-circle`, `mdi-arrow-right`, `mdi-circle`, `mdi-close`, `mdi-rocket-launch-outline`). Depends on T009, T010.
- [X] T014 [P] [US2] Update icon references in `frontend/src/components/SessionPanel.vue` to `$alias` form (`mdi-circle`, `mdi-close`, `mdi-radar`, `mdi-rocket-launch-outline`). Depends on T009, T010.
- [X] T015 [P] [US2] Update icon references in `frontend/src/components/EventCard.vue` to `$alias` form (`mdi-code-json`, `mdi-cog-outline`, `mdi-subdirectory-arrow-right`). Depends on T009, T010.
- [X] T016 [US2] Confirm no `@mdi/font` reference remains anywhere: grep `frontend/index.html`, Dockerfile(s), CSS, and `frontend/src/**` (research.md R4). Depends on T010.
- [X] T017 [US2] Run `cd frontend && npm run build`; verify no `*materialdesignicons*`/MDI `.woff2` in `frontend/dist`, no oversized-asset/chunk warning (SC-004), and compute the reduction vs. the T001 baseline to confirm ≥50% (SC-003; FR-006/FR-008).

**Checkpoint**: US1 and US2 both work independently — webfont gone, build clean, ≥50% lighter, 100% icon parity in both themes.

---

## Phase 5: User Story 3 - Load view code on demand (Priority: P3) — OPTIONAL / best-effort

**Goal**: Code-split the Workflows vs Sessions panels so the default view's initial download excludes the other panel's code. **Not a completion gate** (SC-006 is a target); implement only if the before/after chunk check shows it is worthwhile.

**Independent Test**: Build for production; confirm the default (workflows) entry does not include the sessions panel's code, that switching views fetches its chunk on demand and renders, with a loading indicator when not instantaneous and a clear error if the fetch fails.

### Implementation for User Story 3

- [X] T018 [US3] In `frontend/src/App.vue`, convert the static `WorkflowPanel`/`SessionPanel` imports to `defineAsyncComponent(() => import('./components/…'))` so Vite emits a separate chunk per panel (research.md R3). Depends on US2's App.vue changes (T011).
- [X] T019 [US3] Add the loading and error affordances in `frontend/src/App.vue` per FR-009 (async component `loadingComponent`/`errorComponent`, or the existing app-bar `v-progress-linear` for loading and a clear inline error on failure).
- [X] T020 [US3] Run `cd frontend && npm run build` and inspect emitted chunks: confirm the default-view entry excludes the non-default panel's unique code and that switching fetches a separate chunk (SC-006). If the split proves not worthwhile (shared composables dominate — research.md R3 risk), record that and revert.

**Checkpoint**: All in-scope stories functional; US3 either delivered with affordances or consciously deferred with a note.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and consistency across all stories.

- [X] T021 [P] Run the full test suite: `cd frontend && npm test` (icons + api specs pass) and `cd backend && uv run pytest` (backend unaffected, still green); ensure formatters are clean.
- [ ] T022 [US2] Manual visual-parity check (SC-005, 100%): `npm run dev`, then confirm every icon renders with no missing-glyph boxes across all views in **both** light and dark themes — header status chip + theme toggle (App), bell + read/unread dots (NotificationCenter), rocket/close/alert/arrow (WorkflowPanel), rocket/close/radar (SessionPanel), cog/subdirectory/code-json (EventCard).
- [X] T023 [P] Update any developer-facing docs touched by these changes (`README.md`, `docs/`, `backend/README.md`, `frontend/.env.example` note) so setup/behaviour descriptions stay consistent (FR-010; constitution: docs kept consistent with behaviour).
- [X] T024 Run the `quickstart.md` validation end-to-end and tick the Definition-of-Done gate summary (US1 zero-config + override + docs; US2 no webfont / no warning / ≥50% / parity; tests + formatters green).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately (baseline needed before US2 verification).
- **Foundational (Phase 2)**: Intentionally empty — no blocking foundation for this feature.
- **User Stories (Phase 3–5)**: All independent of one another and may proceed in parallel or in priority order (P1 → P2 → P3).
- **Polish (Phase 6)**: Depends on the in-scope user stories being complete.

### User Story Dependencies

- **US1 (P1)**: Independent. No dependency on US2/US3.
- **US2 (P2)**: Independent of US1. Internal order: T007 (deps) → T008 (test) → T009 (registry) → T010 (main.ts) → T011–T015 (templates, parallel) → T016 (grep) → T017 (build).
- **US3 (P3)**: Optional; touches `App.vue` which US2 also edits (T011), so run US3 **after** US2's `App.vue` change to avoid conflict.

### Within User Story 2

- T007 (dependency swap) before everything else in US2.
- T008 (completeness test) written before implementation and expected to fail.
- T009 (registry) before T010 (main.ts config) before T011–T015 (template `$alias` refs).
- T011–T015 edit five different files → parallelizable.
- T016 (grep) and T017 (build) after templates are updated.

### Parallel Opportunities

- **Across stories**: US1 and US2 can be worked simultaneously (different files entirely; US1 = `.env.example`/`api/index.ts`/docs/backend, US2 = icon plumbing).
- **US1**: T002 (test) and T005 (docs grep) are parallel with the `.env.example`/api tasks.
- **US2**: T011, T012, T013, T014, T015 (five component files) run in parallel after T009/T010.
- **Polish**: T021 and T023 are parallel.

---

## Parallel Example: User Story 2 template updates

```bash
# After T009 (icons.ts) and T010 (main.ts) are done, update all five
# component files in parallel — each is a distinct file:
Task: "Update icon refs in frontend/src/App.vue → $alias form"
Task: "Update icon refs in frontend/src/components/NotificationCenter.vue → $alias form"
Task: "Update icon refs in frontend/src/components/WorkflowPanel.vue → $alias form"
Task: "Update icon refs in frontend/src/components/SessionPanel.vue → $alias form"
Task: "Update icon refs in frontend/src/components/EventCard.vue → $alias form"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Complete Phase 1 (baseline capture — optional for US1 alone but cheap).
2. Complete Phase 3 (US1): `.env.example` fix, API_BASE test, docs consistency, backend confirm.
3. **STOP and VALIDATE**: fresh-checkout zero-config run works; copying `.env.example` doesn't break dev; override wins; docs all say 8000.
4. Ship — this alone removes the highest-leverage papercut.

### Incremental Delivery

1. US1 → test → demo (zero-config MVP).
2. US2 → build/verify → demo (≥50% lighter first load — the hard payload requirement).
3. US3 (optional) → verify chunk split is worthwhile → deliver or defer.
4. Polish → full quickstart + Definition-of-Done gate.

---

## Notes

- [P] tasks = different files, no incomplete-task dependency.
- [Story] label maps each task to its user story for traceability.
- US1 and US2 are the value core; US3 is explicitly optional (SC-006 is a target, not a gate).
- Write the two vitest specs (T002, T008) before their implementation and confirm they fail first (Principle III).
- Preserve the `??` empty-string semantics in `api/index.ts` — do not "fix" it to `||`, which would break the packaged image's same-origin contract.
- Commit after each task or logical group; keep `.env` out of version control (no real `.env` committed).
