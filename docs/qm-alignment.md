# Quartermaster alignment report

Status as of 2026-07-13. **Supersedes the 2026-07-05 pass.** This is a
recurring **alignment pass**: kestrel uses the **Quartermaster** MCP server,
which serves versioned instruction kits for the stacks and capabilities in
play. This report re-infers the repo's traits, pulls the applicable kits'
guidance, assesses how far the current code/docs drift from it, and turns the
gaps into **isolated work-packages** — each scoped to become its own branch/PR
off `master` with no shared state.

This pass was triggered by a **catalog update**. Most of the 2026-07-05 backlog
has since landed (WP1–4, WP7, WP8); this pass records what shipped, folds in
the catalog changes — chiefly a v2 observability refactor (correlation-ID →
OpenTelemetry) implemented here as **WP9** — and carries the still-open items
forward. The goal remains a durable, prioritized backlog, not a big refactor.

## Scope decisions

- **Pragmatic alignment bar.** `contract.md` scopes kestrel as a personal,
  single-user, host-run tool. High/Med gaps (correctness, security posture,
  doc accuracy) are treated as *required*; Low gaps that only matter at
  multi-user / production scale are listed under
  [Deferred](#deferred-single-user-scope) with rationale, not dropped silently.
- **Adopted the v2 observability model.** The catalog's coordinated v2 breaking
  changes (see [Catalog delta](#catalog-delta-since-2026-07-05)) were adopted
  rather than pinned to v1: correlation IDs give way to W3C trace context via
  OpenTelemetry. The chosen majors are recorded in `.quartermaster.toml`.
- **Vuetify remains a decision-gated work-package** (adopt vs. drop) — WP5
  frames the fork rather than pre-deciding it; still open.

## Repo trait profile

From Quartermaster `resolve_kits` (confidence: high; engine: embedding):

- **languages:** python, typescript, javascript
- **frameworks:** fastapi, vue, vuetify, vite, github-actions, alembic,
  sqlalchemy, uv
- **capabilities / contexts:** full-stack monorepo, rest-api, backend,
  frontend, ci, deploy, observability (traces), notifications, release, docs

## Catalog delta since 2026-07-05

The updated catalog changed the observability guidance as one coherent story
and added new kits:

- **`module-http-middleware-hardening` v1 → v2** — drops the mandatory
  `X-Correlation-ID` header; cross-service correlation is now `traceparent`
  (W3C trace context) via OpenTelemetry. Keeps the one-log-line, security
  headers, version header, and rate-limiting rules.
- **`module-logging-structured` v1 → v2** — `JSONFormatter` emits
  `trace_id` / `span_id` (default `"-"`) instead of `correlation_id`; the
  `CorrelationIDFilter` / contextvar / set-clear helpers are removed. The
  fields are enriched onto records by OpenTelemetry's logging instrumentation.
- **`module-opentelemetry` v1 → v2** — sheds `metrics.md`; now owns
  **traces + W3C trace-context only**.
- **`module-observability-metrics` (new)** — owns the Prometheus/VictoriaMetrics
  pull-model `/metrics` surface (moved out of the OpenTelemetry kit).
- **New auth kits** — `module-auth-oidc-python`, `module-auth-oidc-vue`,
  `module-dev-auth-bypass`, `module-oidc-user-provisioning`. All **N/A**:
  kestrel has no auth (reuses the host Claude login).

The three v2 majors are pinned in `.quartermaster.toml` so future runs follow
them and the version advisories stop firing.

## Kit applicability

**Applies:** module-fastapi, module-code-style-python,
module-design-principles, **module-logging-structured (v2)**,
module-observability-healthz, **module-http-middleware-hardening (v2)**,
**module-opentelemetry (v2, adopted)**, module-twelve-factor,
module-testing-strategy, stack-fastapi-vuetify, module-vue-vuetify,
module-ux-principles, module-github-link, module-version-control,
module-calver-release-channels, module-documentation,
module-notification-alarm-discipline.

**Partial:** module-database-postgresql (SQLAlchemy/Alembic patterns apply;
Postgres-specific ones N/A — uses SQLite), module-library-preferences,
module-runtime-config-spa, module-release-metadata, module-design-tokens,
module-operator-docs.

**Deferred (in scope, not implemented):** module-observability-metrics — see
[Deferred](#deferred-single-user-scope).

**N/A (confirmed):** module-auth-\* (no auth; reuses host Claude login —
includes the new `-oidc-python`/`-oidc-vue`, `dev-auth-bypass`, and
`oidc-user-provisioning` kits), module-docs-sphinx and
module-hosting-readthedocs (docs are plain Markdown),
module-dev-tooling-taskfile (uses `scripts/*.sh`, no Taskfile),
release-snapshot (single image, no
upstream→downstream client snapshot), module-onboarding-tour (no first-run
onboarding), module-diagrams (latent — no diagrams exist yet),
module-design-tokens multi-surface codegen (no login/email surfaces).

## What already aligns well

Do not re-do these:

- **Backend architecture:** clean `create_app()` factory, router→service→storage
  layering, domain exceptions mapped to explicit status codes,
  `pydantic-settings` with `KESTREL_` prefix + `.env.example`, Alembic-owned
  schema (zero `create_all`), SQLAlchemy 2.x `select()` with bound params.
- **HTTP middleware (v2-aligned after WP1 + WP9):** pure-ASGI security-headers,
  version-header, and one-line request-logging middleware in the correct LIFO
  order; no bespoke correlation header (correlation rides trace context).
- **Health probes:** `/livez` + `/readyz` + `/healthz` with the compact
  `HealthResponse` schema, 200/503 mapping, and no version fingerprint in the
  body (it rides `X-Kestrel-Version`).
- **Observability logging/tracing:** unified stdout logging with `trace_id` /
  `span_id` fields; OpenTelemetry tracing behind a one-file swappable facade,
  off by default and a clean no-op until a collector is configured.
- **Testing:** ~30 backend pytest modules (hermetic conftest, real migrations)
  and a mirrored Vitest suite (HTTP mocked, real assertions, no snapshot-only).
- **Quality gates:** ruff (80-col) for the backend, ESLint/Prettier for the
  frontend, and cspell + a doc line-length check wired into pre-commit and CI.
- **Release engineering:** CalVer + cascading channels + version-sync guard
  (`scripts/check_version_sync.sh`, `scripts/derive_channels.sh`, `release.yml`
  via `workflow_call`, no `latest` tag) — near-exemplary.
- **GitHub link:** `GithubLink.vue` is a textbook implementation of
  module-github-link (env-driven, hides when blank, `rel=noopener`, tested).
- **Notifications:** signals are classed action-required vs. summary on a quiet
  in-app SSE surface (no OS interrupts), deterministic templating, pluggable
  `Notifier` protocol.
- **Docs:** good audience separation and ~80-col semantic wrapping.

## Work-packages

Priority key: **P1** = required, high value; **P2** = required, pragmatic bar.
Each WP is independent unless a dependency is noted.

| WP | Title | Kits | Priority | Status |
|----|-------|------|----------|--------|
| WP1 | Backend HTTP middleware hardening | http-middleware-hardening | **P1** | done (`f080a44`), v2 in WP9 |
| WP2 | Backend health probes (livez/readyz) | observability-healthz | **P1** | done (`a1c9b97`, `7d61d53`) |
| WP3 | Documentation accuracy + operator runbook | documentation, operator-docs | **P1** | done (`2c0a6fe`) |
| WP4 | Quality gates: lint / format / spellcheck | code-style-python, documentation, stack | P2 | done (`ac8fff5`, `5601016`, `cf1fd92`) |
| WP5 | Frontend Vuetify decision (adopt vs. drop) | vue-vuetify, stack | **P1** | **adopt chosen; deep adoption in progress on `wp5-vuetify-adopt`** |
| WP6 | Frontend design-token single-source | design-tokens | P2 | **folded into WP5** (deep adoption drops the custom palette for Vuetify's built-in themes) |
| WP7 | Frontend API client seams | vue-vuetify | P2 | done (`4e81cef`) |
| WP8 | Notification signal classing | notification-alarm-discipline | P2 | done (`55161df`) |
| WP9 | v2 OpenTelemetry migration | opentelemetry, http-middleware-hardening, logging-structured | **P1** | **done (this pass)** |

### WP9 — v2 OpenTelemetry migration (P1, done this pass)

**Kits:** module-opentelemetry (v2), module-http-middleware-hardening (v2),
module-logging-structured (v2).

**Gap:** the landed WP1 implemented the v1 correlation-ID model
(`X-Correlation-ID` middleware + a `correlation_id` log field) that all three
kits removed at v2. The repo was on the frozen-v1 approach with no trace
context.

**Done:**

- `middleware.py` — `RequestLoggingMiddleware` no longer generates, reads, or
  echoes a correlation header; keeps the single structured log line and
  log-then-reraise. Security + version headers unchanged.
- `logging_config.py` — dropped the contextvar, the `set/clear/get` helpers,
  and `CorrelationIDFilter`; added `TraceContextFilter` and a `JsonFormatter`
  that emits `trace_id` / `span_id` from the OTel-injected record attributes
  (`otelTraceID` / `otelSpanID`), defaulting to `"-"`. Text format shows
  `[trace_id]`.
- `telemetry.py` (new) — the **only** OpenTelemetry importer: a `span()` /
  `record_exception()` facade plus `init_tracing(app, settings)`. Off by
  default (`KESTREL_OTEL_ENABLED=false`) and a clean no-op when off; when on,
  installs a parent-based ratio-sampled OTLP tracer and auto-instruments
  FastAPI + logging. Metrics exporter set to `none` (owned by the deferred
  metrics kit).
- `config.py` / `main.py` — added `otel_enabled` / `otel_service_name`
  settings; `create_app()` calls `telemetry.init_tracing`.
- Tests — `test_middleware.py` asserts **no** correlation header;
  `test_logging_config.py` asserts trace-context fields; new `test_telemetry.py`
  exercises the facade with an in-memory span exporter and the disabled no-op.
- Docs — `docs/observability.md` (new Tracing section) and
  `docs/configuration.md` (`KESTREL_OTEL_*` + standard `OTEL_*` vars).
- `.quartermaster.toml` pins the three kits to v2.

**Files:** `backend/app/middleware.py`, `backend/app/logging_config.py`,
`backend/app/telemetry.py`, `backend/app/config.py`, `backend/app/main.py`,
`backend/tests/test_middleware.py`, `backend/tests/test_logging_config.py`,
`backend/tests/test_telemetry.py`, `docs/observability.md`,
`docs/configuration.md`, `.quartermaster.toml`, `backend/pyproject.toml`.

**Verify:** `uv run pytest`; `curl -i` a route → no `X-Correlation-ID`, still
carries the three security headers + `X-Kestrel-Version`; JSON logs show
`trace_id` = `"-"` with tracing off and a real id when
`KESTREL_OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT` are set;
`grep -rn "import opentelemetry"
backend/app` returns only `telemetry.py`.

### WP5 — Frontend Vuetify: adopt (P1, decided; deep adoption in progress)

**Decision (2026-07-15):** **adopt**, and go deep. The initial adoption
(`19ab696`) was cosmetic — Vuetify was wired up but almost no `<v-*>`
components were used. The follow-on work on branch `wp5-vuetify-adopt` migrates
the hand-rolled markup to Vuetify Material components, drops the custom palette
for Vuetify's built-in light+dark themes (with an in-app toggle), and collapses
the shared console shell — prioritising maintainability / CSS reduction. This
subsumes WP6 (below). The original decision framing is kept for context.


**Kits:** module-vue-vuetify, stack-fastapi-vuetify.

**Gap (largest open finding):** Vuetify 4 is installed and a `missionControl`
theme is built in `main.ts`, but `grep '<v-'` over `frontend/src` returns
**zero** Vuetify components — the whole UI is hand-rolled `<div>/<button>` +
`theme.css`. The dependency is dead weight and the kit's conventions
(theme-sourced colours, page-level `v-progress-linear`) are unmet.

**Step 0 — decide (owner call):**

- **Drop:** remove the `vuetify` dependency + `createVuetify` block; declare
  the hand-rolled UI the aligned state; fold theme back into `theme.css`.
- **Adopt:** migrate primitives to Vuetify components, single-source the theme
  via Vuetify `variables` (both `light` + `dark`), and add the mandatory
  page-level `v-progress-linear` driven by the existing `loading` refs.
- Either branch also fixes the trivial a11y gap: add `aria-pressed` to the
  "Workflows" toggle (`App.vue`) for parity with the sessions toggle.

**Files:** `frontend/package.json`, `frontend/src/main.ts`, `App.vue`,
`components/*`, `styles/theme.css`.

**Verify:** `npm run build` + `npm run test`; UI unchanged (drop) or visually
equivalent with Vuetify (adopt); loading indicator visible on initial fetch.

### WP6 — Frontend design-token single-source (P2, folded into WP5)

**Superseded by WP5's deep adoption:** rather than single-sourcing the custom
palette, the deep-adoption work drops the custom palette entirely in favour of
Vuetify's built-in `light`/`dark` themes, which removes the duplication this WP
targeted. The original framing is kept for context.


**Kit:** module-design-tokens.

**Gap:** the palette is duplicated — hex in `main.ts` **and** CSS vars in
`theme.css` — with no linkage, plus stray literals (component gradients / rgba
glows). Only a `dark` theme is defined.

**Do:** collapse to one authoritative token source (Vuetify `variables` if WP5
adopts, else `theme.css`), reference it everywhere, and pull the stray literals
into tokens. Multi-surface codegen (login/email) is **N/A** — no such surfaces.

**Files:** `frontend/src/main.ts`, `styles/theme.css`, offending components.

**Verify:** `grep` for raw hex/rgba in components returns only the token source;
`npm run build`.

## Deferred (single-user scope)

Each is a real kit deviation, downgraded by the pragmatic bar; revisit if
kestrel ever goes multi-user or is exposed beyond localhost.

- **Application metrics** (module-observability-metrics, new) — the pull model
  needs a Prometheus/VictoriaMetrics scraper; a single-user localhost tool has
  none. If added later: expose `/metrics` with the standard Python client,
  bounded labels, one worker per container. Traces (WP9) already cover
  request-level introspection.
- **Live trace collector/exporter** (opentelemetry) — the tracing facade ships
  and is v2-aligned, but tracing stays **off by default**; standing up an OTLP
  collector is out of scope for a personal tool. Flip `KESTREL_OTEL_ENABLED`
  when one exists.
- **Rate limiting** (http-middleware-hardening) — localhost single-user; noted
  in `main.py`'s middleware-ordering comment.
- **Build-once runtime config** (runtime-config-spa) — the packaged image sets
  `VITE_API_BASE=` empty → same-origin, so one image already serves any
  environment; the kit's runtime-global *mechanism* is absent but the *outcome*
  is met.
- **Release-metadata BuildMeta surface** (release-metadata) — commit SHA /
  build time not exposed in the SPA; cheap to add later if desired.
- **DB timezone-aware timestamps / request-scoped `get_db`**
  (database-postgresql) — deliberate deviation; documented in WP3.
- **Backend config micro-hygiene** — `KESTREL_RELOAD/HOST/PORT` read via
  `os.environ` in `__main__.py`; promote to `Settings` fields when convenient.
- **Notification service layer** — `routers/notifications.py` calls the store
  directly; a thin `NotificationService` would restore strict layering (Low).
- **i18n label** (github-link) — no i18n infrastructure exists; N/A until one
  is introduced.
- **Architecture context diagram** (diagrams) — enhancement; if added, follow
  module-diagrams (Okabe-Ito, labeled edges). Also flag the red/green
  `--err`/`--ok` status pairing in `docs/design-palette.md` for a non-color
  cue.

## Catalog health (feedback for the QM owner)

Surfaced by this pass (via `list_kits`, `resolve_kits`, `evaluate_catalog`);
these affect kestrel's runs but are catalog-side fixes:

- **`module-logging-structured` is unloadable.** `get_kit` fails for every
  section (`section file 'overview' does not exist`), and the kit is absent
  from `list_kits` / `resolve_kits`. A kit the repo depends on cannot be read;
  WP9's logging changes were implemented from the version-advisory summary.
- **Stray `test` placeholder kit** surfaces in `resolve_kits` (score 50).
- **`evaluate_catalog`: 4 failing cases** — the `oidc` (auth kits) and
  `observability` (metrics) capabilities are not inferred from plain task text,
  so those kits self-rank `null` and need explicit trait selection to surface.

## Overall verification

- **Backend:** `cd backend && uv run pytest` green after each backend WP.
- **Lint:** `uvx ruff check backend` clean (80-col).
- **Frontend:** `cd frontend && npm run test && npm run build` green after each
  frontend WP.
- **Release invariants untouched:** `bash scripts/check_version_sync.sh` passes.
- **Doc gates:** `pre-commit run --all-files` clean.
- **Runtime smoke:** build the image (`docker compose build`), start it, and
  `curl` `/livez`, `/readyz`, `/healthz` plus a normal route to confirm headers
  and (with tracing enabled) trace-linked logs.
- Each open WP ships as its own branch off `master` with a Conventional-Commit
  message and green CI before merge.
