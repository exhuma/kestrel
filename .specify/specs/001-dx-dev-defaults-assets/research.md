# Phase 0 Research: DX polish — zero-config dev servers & lighter frontend assets

All Technical Context items were resolvable from the codebase and Vuetify 4's
installed iconsets; no open `NEEDS CLARIFICATION` remain.

## R1. Icon delivery: SVG iconset vs. webfont

**Decision**: Switch Vuetify's icon set from the **MDI webfont** (`@mdi/font`,
imported as global CSS) to Vuetify's built-in **`mdi-svg` iconset** backed by
tree-shaken imports from **`@mdi/js`**. Register each of the 13 used glyphs as a
Vuetify **alias** in a new `src/plugins/icons.ts`, and reference them as
`$name` in templates.

**Rationale**:
- `@mdi/font` ships the *entire* icon set — a ~403 kB `.woff2` (plus larger
  ttf/eot/woff fallbacks) and an inflated stylesheet — regardless of how few
  glyphs are used. The app uses **13** glyphs.
- `@mdi/js` exports each icon as an SVG path string; unused exports are
  tree-shaken by Vite, so only the 13 referenced paths ship (a few kB).
- `vuetify/lib/iconsets/mdi-svg` is present in the installed Vuetify 4 and is
  the framework's own, battle-tested SVG renderer (correct 24×24 viewBox,
  `currentColor` theming, sizing). Using it keeps us kit-aligned (framework
  mechanism over a bespoke component) and avoids rendering-regression risk.

**Enumerated glyphs** (name → `@mdi/js` export):

| Template name | `@mdi/js` export | Files |
|---|---|---|
| `mdi-alert-circle` | `mdiAlertCircle` | WorkflowPanel |
| `mdi-arrow-right` | `mdiArrowRight` | WorkflowPanel |
| `mdi-bell` | `mdiBell` | NotificationCenter |
| `mdi-circle` | `mdiCircle` | App, NotificationCenter, WorkflowPanel, SessionPanel |
| `mdi-circle-outline` | `mdiCircleOutline` | App, NotificationCenter |
| `mdi-close` | `mdiClose` | WorkflowPanel, SessionPanel |
| `mdi-code-json` | `mdiCodeJson` | EventCard |
| `mdi-cog-outline` | `mdiCogOutline` | EventCard |
| `mdi-radar` | `mdiRadar` | SessionPanel |
| `mdi-rocket-launch-outline` | `mdiRocketLaunchOutline` | WorkflowPanel, SessionPanel |
| `mdi-subdirectory-arrow-right` | `mdiSubdirectoryArrowRight` | EventCard |
| `mdi-weather-night` | `mdiWeatherNight` | App |
| `mdi-weather-sunny` | `mdiWeatherSunny` | App |

All 13 references are **string literals** (some inside ternaries, e.g.
`:icon="running ? 'mdi-circle' : 'mdi-circle-outline'"`); none are constructed
from runtime data, so the set is fully enumerable and a completeness test can
guard it.

**Alternatives considered**:
- *Custom name-preserving icon set* (a bespoke Vuetify `IconSet` whose component
  maps `mdi-close` → an imported path, keeping template strings unchanged). Zero
  template churn, but re-implements sizing/colour/viewBox that the built-in
  `mdi-svg` set already handles correctly — added complexity and regression risk
  for the sake of avoiding 13 mechanical renames. **Rejected** (Principle IV /
  minimal-risk).
- *Subsetting the webfont* (ship only used glyphs as a trimmed font). Keeps a
  font-loading path and adds a build-time subsetting tool/dependency. Heavier
  and less idiomatic than SVG. **Rejected**.
- *Keep `@mdi/font`, accept the weight.* Fails SC-003/SC-004 intent. **Rejected**.

**Migration mechanics** (for tasks/impl, not exhaustive code):
- `main.ts`: remove `import '@mdi/font/css/materialdesignicons.css'`; add
  `icons: { defaultSet: 'mdi', aliases, sets: { mdi } }` where `mdi` comes from
  `vuetify/lib/iconsets/mdi-svg` and `aliases` from the new `plugins/icons.ts`.
- Templates: change each `mdi-foo` → `$foo` (13 references, 5 files).
- `package.json`: add `@mdi/js`, remove `@mdi/font`.
- Confirm nothing else imports `@mdi/font` (verified: only `main.ts:4`).

## R2. Zero-config dev: canonical port & API base

**Decision**: Canonical dev port is **8000** everywhere (resolved in spec
clarifications). No backend code change: `uvicorn app.main:app --reload`
defaults to :8000 and `workspace_root` already defaults to
`./.kestrel-workspaces`. The frontend `API_BASE` already defaults to
`http://localhost:8000` via the in-code fallback. **No committed `.env`.**

**Rationale**: Everything (README, `docs/`, docker, getting-started) already
uses 8000, and the code defaults already match. US1 is therefore *mostly already
satisfied* — the work is to remove one friction point and verify, not to build
new configuration.

**Finding — `.env.example` empty-string footgun**: `api/index.ts` uses
`import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'`. Nullish coalescing
(`??`) only falls back on `undefined`/`null`, **not** on empty string. The
committed `frontend/.env.example` contains `VITE_API_BASE=` (empty). A developer
who copies `.env.example` → `.env.local` verbatim gets `VITE_API_BASE === ''`,
so `API_BASE` becomes `''` (same-origin → Vite :5173, which has no API) and the
UI silently fails to reach the backend.

**Decision**: Comment out the `VITE_API_BASE=` line in `.env.example`
(`# VITE_API_BASE=`), so copying the file leaves the var **unset** and dev falls
through to the `:8000` default. This preserves the existing three-way semantics
without changing app code:
- **unset** (dev, or copied example) → `http://localhost:8000` default,
- **empty string** (packaged image build-arg) → same-origin,
- **explicit value** → that value (satisfies FR-004 override).

Optionally add a defensive guard in `api/index.ts` treating a blank/whitespace
value as unset **for dev only**, but this risks the packaged image's
intentional empty-string=same-origin contract; the doc fix is lower-risk and
sufficient. Tasks will keep the app-code semantics as-is and cover the default
resolution with a unit test.

**Alternatives considered**:
- *Change `??` to `||`.* Would make empty string fall back to `:8000`, breaking
  the packaged image's `empty = same-origin` contract. **Rejected**.
- *Commit a real `frontend/.env`.* Forbidden by the constitution
  (`.env` stays out of version control). **Rejected** (already decided).

## R3. Panel code-splitting (optional, US3)

**Decision**: If implemented, convert the static
`import SessionPanel/WorkflowPanel` in `App.vue` to
`defineAsyncComponent(() => import('./components/...'))`. Provide a loading
affordance (the existing app-bar `v-progress-linear`, or the async component's
`loadingComponent`) and an error affordance (`errorComponent`) per FR-009.

**Rationale**: Vite emits a separate chunk per dynamic `import()`, so the
default view (`workflows`) no longer bundles the other panel. Marginal versus
the icon win, hence optional/best-effort; SC-006 is a target, not a gate.

**Risk/limits**: The two panels share composables (`useSessions`,
`useWorkflows`) already imported eagerly in `App.vue` for header state, so the
split saves only each panel's unique template/logic, not the shared composables.
Worth a quick before/after chunk check to confirm the split is worthwhile before
committing to it.

**Alternatives considered**: Route-based splitting — rejected, the app has no
router (a single `App.vue` with a `v-btn-toggle` view switch).

## R4. Both run modes stay working

**Decision / checks for impl**: Confirm no reference to `@mdi/font` remains in
`index.html`, Dockerfile(s), or CSS (verified: only `main.ts`). Confirm the
production `npm run build` (`vue-tsc -b && vite build`) succeeds after the swap
and emits no oversized-asset warning. Confirm the bundled image still serves
same-origin (unaffected — icon paths ship inside JS; `.env.example` change does
not touch the packaged build).

## Baseline for SC-003 (to re-measure at implementation time)

- Current: JS ~458 kB, CSS ~649 kB, MDI `.woff2` ~403 kB (on-disk `@mdi/font`
  ≈ 5.8 MB across all font formats + CSS).
- Expected after: MDI webfont gone; CSS drops to roughly the Vuetify-component
  baseline; 13 SVG paths add a few kB to JS. Uncompressed first-load payload
  falls well over the 50% SC-003 threshold. Exact figures re-measured from the
  post-change `vite build` output.
