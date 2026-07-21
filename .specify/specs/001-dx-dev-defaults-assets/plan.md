# Implementation Plan: DX polish — zero-config dev servers & lighter frontend assets

**Branch**: `001-dx-dev-defaults-assets` | **Date**: 2026-07-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `.specify/specs/001-dx-dev-defaults-assets/spec.md`

## Summary

Two developer-experience fixes, both frontend/build-scoped:

1. **Lighter first load (hard requirement, US2)** — replace the full Material
   Design Icons **webfont** (`@mdi/font`, ~403 kB `.woff2` + heavily inflated
   CSS) with Vuetify's **SVG icon set** backed by `@mdi/js`, so only the 13
   glyphs the UI actually references are shipped (tree-shaken). This removes the
   single largest avoidable item in the first-load payload.
2. **Zero-config dev servers (US1)** — confirm and harden the run-from-source
   path so `uv run uvicorn app.main:app --reload` (backend, :8000) and
   `npm run dev` (frontend, :5173) work with **no environment variables**. The
   in-code `API_BASE` default already targets `http://localhost:8000`; the only
   real gap is a `.env.example` footgun that breaks dev if the file is copied
   verbatim. Documentation is aligned to a single canonical port (8000).
3. **Optional (US3, best-effort)** — code-split the Workflows vs Sessions panels
   via dynamic `import()` so the default view's initial download excludes the
   other panel's code. Not a completion gate.

Technical approach validated against the codebase: Vuetify 4 ships
`vuetify/lib/iconsets/mdi-svg`; `@mdi/js` must be added and `@mdi/font` removed;
all 13 icon references are string literals in 5 components.

## Technical Context

**Language/Version**: TypeScript 5/6 (frontend), Python 3.12 (backend — untouched by this feature)

**Primary Dependencies**: Vue 3.5, Vuetify 4.1, Vite 8, `@mdi/js` (new) replacing `@mdi/font` (removed); `vite-plugin-vuetify` (auto-import/tree-shake, already present)

**Storage**: N/A (no data-model or persistence change)

**Testing**: vitest (frontend); pytest (backend — no new backend behaviour, so no new backend tests beyond confirming nothing broke)

**Target Platform**: Browser SPA + FastAPI service (localhost dev + bundled Docker image)

**Project Type**: Web application (`backend/` + `frontend/`)

**Performance Goals**: First-load asset payload (JS+CSS+fonts, uncompressed) reduced ≥50% (SC-003); production build emits no oversized-asset warnings (SC-004)

**Constraints**: Both run modes (bundled Docker image, run-from-source) MUST keep working; no committed `.env`; every icon that rendered before MUST still render in both themes (SC-005, 100%)

**Scale/Scope**: 5 frontend components touched (13 icon references), `main.ts`, `package.json`, `frontend/.env.example`, and developer docs. No backend code changes expected.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment | Status |
|-----------|-----------|--------|
| I. Contract Fidelity | UI/build-only change; no `frontend/src/types/` ↔ backend JSON shapes touched. Icon-set switch uses Vuetify's own SVG mechanism — a stack-aligned choice, not a recorded deviation. | ✅ Pass |
| II. Layered, Backend-Owned Architecture | No business logic moves to the frontend; backend untouched. | ✅ Pass |
| III. Test-First (NON-NEGOTIABLE) | Add vitest coverage: (a) `API_BASE` default resolution incl. the empty-string case; (b) a guard asserting every used `mdi-*` name resolves to an alias/SVG path (prevents missing-glyph regressions). HTTP mocked; no real DB/subprocess. | ✅ Pass (tests planned) |
| IV. Deliberate Simplicity & Single-User Scope | Net dependency count unchanged: `@mdi/js` **replaces** `@mdi/font`. Justified: ships only referenced glyphs, ~400 kB saved. No speculative generality. | ✅ Pass |
| V. Kit-Aligned Consistency & Observability | Icons sourced through the Vuetify icon system (no hard-coded colours). Secrets: no committed `.env`; `.env.example` remains the template. Logging/health endpoints untouched. | ✅ Pass |

**Run-mode gate**: Bundled image serves the SPA same-origin; the icon change is
build-time only and the `.env.example` change does not affect the packaged build
(which sets `VITE_API_BASE` explicitly). Both modes preserved. ✅

No violations → Complexity Tracking table left empty.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/001-dx-dev-defaults-assets/
├── plan.md              # This file
├── research.md          # Phase 0 — icon-set migration & env-default decisions
├── data-model.md        # Phase 1 — icon alias registry (config artifact); no entities
├── quickstart.md        # Phase 1 — how to validate US1/US2/US3
├── contracts/
│   └── README.md        # Phase 1 — states no external/API contract changes
└── tasks.md             # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

```text
frontend/
├── package.json                     # + @mdi/js, − @mdi/font
├── .env.example                     # de-footgun the VITE_API_BASE line
├── src/
│   ├── main.ts                      # drop @mdi/font CSS import; configure Vuetify mdi-svg iconset + aliases
│   ├── plugins/icons.ts             # NEW: tree-shaken @mdi/js imports → Vuetify aliases map
│   ├── api/index.ts                 # (verify) API_BASE default; harden empty-string handling
│   ├── App.vue                      # 2 icon refs; (optional US3) async panel imports
│   └── components/
│       ├── NotificationCenter.vue   # 3 icon refs
│       ├── WorkflowPanel.vue        # 5 icon refs
│       ├── SessionPanel.vue         # 4 icon refs
│       └── EventCard.vue            # 3 icon refs
└── tests/
    ├── plugins/icons.spec.ts        # NEW: every used mdi-* name resolves to a path
    └── api/index.spec.ts            # NEW/extend: API_BASE default resolution

backend/                              # NO code changes expected
docs/                                 # verify port/setup consistency (already :8000)
```

**Structure Decision**: Existing two-package web-app layout (`backend/` +
`frontend/`). All changes are in `frontend/` plus a documentation consistency
pass; the backend is confirmed unchanged (uvicorn's default :8000 and the
`workspace_root` default already satisfy FR-001/FR-005).

## Complexity Tracking

> No Constitution Check violations — table intentionally empty.
