# Phase 1 Data Model: DX polish — zero-config dev servers & lighter frontend assets

This feature introduces **no persistent entities**, no database schema changes,
and no backend data structures. It is UI/build-scoped. The only structured
artifact is a frontend config map, documented here for completeness.

## Icon Alias Registry (frontend config, not persisted)

**Location**: `frontend/src/plugins/icons.ts` (new)

**Purpose**: Map the application's icon alias names to tree-shaken SVG path
strings imported from `@mdi/js`, for registration as Vuetify icon aliases.

**Shape**: `Record<string, string>` — alias name → SVG path `d` string.

**Entries** (13, exhaustive — see research.md R1 for the file cross-reference):

| Alias (`$name` in templates) | Source export (`@mdi/js`) |
|---|---|
| `alertCircle` | `mdiAlertCircle` |
| `arrowRight` | `mdiArrowRight` |
| `bell` | `mdiBell` |
| `circle` | `mdiCircle` |
| `circleOutline` | `mdiCircleOutline` |
| `close` | `mdiClose` |
| `codeJson` | `mdiCodeJson` |
| `cogOutline` | `mdiCogOutline` |
| `radar` | `mdiRadar` |
| `rocketLaunchOutline` | `mdiRocketLaunchOutline` |
| `subdirectoryArrowRight` | `mdiSubdirectoryArrowRight` |
| `weatherNight` | `mdiWeatherNight` |
| `weatherSunny` | `mdiWeatherSunny` |

**Validation rule (enforced by test, Principle III)**: the set of alias keys
MUST cover every `mdi-*` glyph referenced in `frontend/src/**` — a vitest guard
greps the source for `mdi-[a-z-]+` usages (mapped to their alias) and asserts
each resolves to a non-empty path, preventing missing-glyph regressions when new
icons are added later.

**Lifecycle**: Static, compile-time. No runtime mutation, no persistence.

## Configuration values (existing, unchanged in code)

| Value | Source | Default | Notes |
|---|---|---|---|
| Backend dev port | uvicorn CLI | 8000 | No app setting; documented canonical port. |
| `workspace_root` | `Settings` (pydantic-settings) | `./.kestrel-workspaces` | Already defaulted; no change. |
| `API_BASE` | `import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'` | `http://localhost:8000` | Unchanged; empty-string semantics preserved (see research.md R2). |

No new configuration keys are added.
