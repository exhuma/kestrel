# Quartermaster alignment report

Status as of 2026-07-05. This is a one-off **alignment pass**: kestrel uses the
**Quartermaster** MCP server, which serves versioned instruction kits for the
stacks and capabilities in play. This report infers the repo's traits, pulls
the applicable kits' guidance, assesses how far the current code/docs drift
from it, and turns the gaps into **isolated work-packages** — each one scoped
to become its own branch/PR off `master` with no shared state.

The goal is a durable, prioritized backlog, not a single big refactor.

## Scope decisions

- **Pragmatic alignment bar.** `contract.md` scopes kestrel as a personal,
  single-user, host-run tool. High/Med gaps (correctness, security posture,
  doc accuracy) are treated as *required*; Low gaps that only matter at
  multi-user / production scale are listed under
  [Deferred](#deferred-single-user-scope) with rationale, not dropped silently.
- **Vuetify is a decision-gated work-package** (adopt vs. drop) — WP5 frames
  the fork rather than pre-deciding it.

## Repo trait profile

From Quartermaster `resolve_kits` (confidence: high):

- **languages:** python, typescript, javascript
- **frameworks:** fastapi, vue, vuetify, vite, github-actions, alembic,
  sqlalchemy, uv
- **capabilities / contexts:** full-stack monorepo, rest-api, backend,
  frontend, ci, deploy, observability, notifications, release, docs

## Kit applicability

**Applies:** module-fastapi, module-code-style-python,
module-design-principles, module-logging-structured,
module-observability-healthz, module-http-middleware-hardening,
module-twelve-factor, module-testing-strategy, stack-fastapi-vuetify,
module-vue-vuetify, module-ux-principles, module-github-link,
module-version-control, module-calver-release-channels, module-documentation,
module-notification-alarm-discipline.

**Partial:** module-database-postgresql (SQLAlchemy/Alembic patterns apply;
Postgres-specific ones N/A — uses SQLite), module-library-preferences,
module-runtime-config-spa, module-release-metadata, module-design-tokens,
module-operator-docs.

**N/A (confirmed):** module-auth-\* (no auth; reuses host Claude login),
module-docs-sphinx and module-hosting-readthedocs (docs are plain Markdown),
module-dev-tooling-taskfile (uses `scripts/*.sh`, no Taskfile),
release-snapshot (single image, no upstream→downstream client snapshot),
module-onboarding-tour (no first-run onboarding), module-diagrams (latent — no
diagrams exist yet), module-design-tokens multi-surface codegen (no
login/email surfaces).

## What already aligns well

Do not re-do these:

- **Backend architecture:** clean `create_app()` factory, router→service→storage
  layering, domain exceptions mapped to explicit status codes,
  `pydantic-settings` with `KESTREL_` prefix + `.env.example`, Alembic-owned
  schema (zero `create_all`), SQLAlchemy 2.x `select()` with bound params.
- **Testing:** ~30 backend pytest modules (hermetic conftest, real migrations)
  and a mirrored Vitest suite (HTTP mocked, real assertions, no snapshot-only).
- **Release engineering:** CalVer + cascading channels + version-sync guard
  (`scripts/check_version_sync.sh`, `scripts/derive_channels.sh`, `release.yml`
  via `workflow_call`, no `latest` tag) — near-exemplary.
- **GitHub link:** `GithubLink.vue` is a textbook implementation of
  module-github-link (env-driven, hides when blank, `rel=noopener`, tested).
- **Notifications:** all signals land on a quiet in-app SSE surface (no OS
  interrupts), deterministic templating, pluggable `Notifier` protocol.
- **Docs:** good audience separation and ~80-col semantic wrapping.

## Work-packages

Priority key: **P1** = required, high value; **P2** = required, pragmatic bar.
Each WP is independent unless a dependency is noted.

| WP | Title | Kits | Priority | Depends on |
|----|-------|------|----------|-----------|
| WP1 | Backend HTTP middleware hardening | http-middleware-hardening, logging-structured | **P1** | — |
| WP2 | Backend health probes (livez/readyz) | observability-healthz | **P1** | WP1 |
| WP3 | Documentation accuracy + operator runbook | documentation, operator-docs | **P1** | — |
| WP4 | Quality gates: lint / format / spellcheck | code-style-python, documentation, stack | P2 | — |
| WP5 | Frontend Vuetify decision (adopt vs. drop) | vue-vuetify, stack | **P1** | — |
| WP6 | Frontend design-token single-source | design-tokens | P2 | WP5 |
| WP7 | Frontend API client seams | vue-vuetify | P2 | — |
| WP8 | Notification signal classing | notification-alarm-discipline | P2 | — |

### WP1 — Backend HTTP middleware hardening (P1)

**Kits:** module-http-middleware-hardening, module-logging-structured
(correlation-id).

**Gap:** `backend/app/main.py` registers only `CORSMiddleware`. No
correlation-ID handling, no security headers, no version response header, no
per-request structured log line. `backend/app/logging_config.py`'s
`JsonFormatter` emits no `correlation_id`.

**Do:**

- Add a request middleware that honours/generates `X-Correlation-ID`, stores it
  in a `contextvar`, echoes it on the response, and clears it in all paths.
- Add a logging filter in `logging_config.py` that injects `correlation_id`
  into every record; include it in the JSON payload.
- Add a `SecurityHeadersMiddleware` (`X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`).
- Add a version response header (`X-Kestrel-Version`) from `settings.version`.
- Emit one structured request-log line (method/path/status/duration).
- Add a middleware-ordering comment (CORS outermost; LIFO discipline).
- **Deferred:** rate limiting (`limits`) — single-user localhost; note it in the
  ordering comment for the future.

**Files:** `backend/app/main.py`, `backend/app/logging_config.py`.

**Verify:** `uv run pytest`; `curl -i` a route and confirm the three security
headers, `X-Kestrel-Version`, and an echoed `X-Correlation-ID`; confirm JSON
logs carry `correlation_id`.

### WP2 — Backend health probes (P1, depends on WP1 for the version header)

**Kit:** module-observability-healthz.

**Gap:** only `GET /healthz` exists (`main.py:121`), doing a DB `SELECT 1`
(that's readiness); no `/livez` / `/readyz`. The response uses a non-standard
`unavailable` token and returns a `version` fingerprint in the body (the kit
forbids version fingerprints in the payload). Note `docs/next-steps.md:49`
still claims "No `/health` endpoint" — also stale.

**Do:**

- Add `/livez` (process-only, no external deps) and `/readyz` (DB check).
- Adopt the compact `HealthResponse{probe,status,checked_at,components[]}`
  schema with `ok|degraded|fail|unknown` + 200/503 mapping; keep `/healthz` as
  a summary.
- Drop `version` from the health body (it now rides the response header from
  WP1).
- Point the Docker `HEALTHCHECK` (`Dockerfile:80`) at `/livez`.
- Update `docs/observability.md` and the stale `docs/next-steps.md` note.

**Files:** `backend/app/main.py`, `Dockerfile`, `docs/observability.md`.

**Verify:** `uv run pytest`; `curl` all three endpoints; confirm 503 when the DB
is unreachable; container reports healthy.

### WP3 — Documentation accuracy + operator runbook (P1)

**Kits:** module-documentation, module-operator-docs.

**Gaps:**

- `contract.md:15-19` is **stale** — claims "in-memory only, no database, no
  auth, NOT in Docker, Dockerisation deferred", but the repo ships
  SQLite + SQLAlchemy + Alembic and a Docker image.
- `docs/setup-github-workflow.md:21` points operators at
  `backend/app/config.py` to discover config, and mixes from-source dev steps
  into operator token setup.
- No operator **Upgrade / backup** guidance despite auto-migrations on
  container start.
- `docs/configuration.md:71-72` leaks a build mechanism (`KESTREL_VERSION`
  baked at build).

**Do:**

- Update/retire `contract.md` (mark superseded by `docs/architecture.md`), or
  rewrite it to current reality; document the *deliberate* DB deviations here
  (store-owned sessions instead of a request-scoped `get_db`; naive `DateTime`
  timestamps) so they read as intentional, not omissions.
- In `setup-github-workflow.md`, enumerate the three `KESTREL_GITHUB_*`
  settings in-doc; move from-source run steps to `docs/development.md`.
- Add an **Upgrading** section (pin image tag for prod; back up the
  `kestrel-data`/SQLite volume before pulling a new tag).
- Reword the version note to "read-only; reports the running build."

**Files:** `contract.md`, `docs/setup-github-workflow.md`,
`docs/configuration.md`, `docs/development.md`, `docs/architecture.md`.

**Verify:** read-through; every config value an operator needs is present
without opening source.

### WP4 — Quality gates: lint / format / spellcheck (P2)

**Kits:** module-code-style-python, module-documentation, stack-fastapi-vuetify.

**Gap:** no linters/formatters/spellcheck anywhere. Backend `pyproject.toml`
has no ruff/black; TS/Vue has no ESLint/Prettier; several lines exceed 80 cols
(`backend/app/models.py:621`, `frontend/src/components/WorkflowPanel.vue`
~37 lines); no `cspell`/`proselint`/pre-commit.

**Do:**

- Backend: add **ruff** (`line-length=80`, import rules) to `pyproject.toml`;
  hoist in-function imports in `main.py`/`config.py` where no import cycle
  exists (leave documented cycle-breakers).
- Frontend: add **ESLint + Prettier** (80-col) config.
- Docs/repo: add `cspell.json` + project dictionary and a
  `.pre-commit-config.yaml` wiring cspell + a line-length/`MD013` check
  (proselint opt-in, scoped off runbooks).
- Wire lint into `.github/workflows/testing.yml`.
- Split allowed: this WP may ship as three sub-PRs (backend / frontend / docs)
  if a single PR is too broad.

**Files:** `backend/pyproject.toml`, new `frontend/.eslintrc*` + `.prettierrc`,
`cspell.json`, `.pre-commit-config.yaml`, `.github/workflows/testing.yml`.

**Verify:** `ruff check`, `npm run lint`, `pre-commit run --all-files`, CI green.

### WP5 — Frontend Vuetify decision: adopt vs. drop (P1, decision-gated)

**Kits:** module-vue-vuetify, stack-fastapi-vuetify.

**Gap (largest single finding):** Vuetify 4 is installed and a `missionControl`
theme is built in `main.ts:11-32`, but `grep '<v-'` over `frontend/src` returns
**zero** Vuetify components — the whole UI is hand-rolled `<div>/<button>` +
`theme.css`. The dependency is dead weight and the kit's conventions
(theme-sourced colours, page-level `v-progress-linear`) are unmet.

**Step 0 — decide (owner call):**

- **Drop:** remove the `vuetify` dependency + `createVuetify` block; declare
  the hand-rolled UI the aligned state; fold theme back into `theme.css`
  cleanly.
- **Adopt:** migrate primitives to Vuetify components, single-source the theme
  via Vuetify `variables` (both `light` + `dark`), and add the mandatory
  page-level `v-progress-linear` (`absolute`, `location="bottom"`,
  `indeterminate`) driven by the existing `loading` refs
  (`composables/useSessions.ts:7`).
- Either branch also fixes the trivial a11y gap: add `aria-pressed` to the
  "Workflows" toggle (`App.vue:29-30`) for parity with the sessions toggle.

**Files:** `frontend/package.json`, `frontend/src/main.ts`, `App.vue`,
`components/*`, `styles/theme.css`.

**Verify:** `npm run build` + `npm run test`; UI unchanged (drop) or visually
equivalent with Vuetify (adopt); loading indicator visible on initial fetch.

### WP6 — Frontend design-token single-source (P2, depends on WP5)

**Kit:** module-design-tokens.

**Gap:** the palette is duplicated — hex in `main.ts:20-27` **and** CSS vars in
`theme.css:9-37` — with no linkage, plus stray literals
(`WorkflowPanel.vue:586` gradient; `NotificationCenter.vue:58` / `App.vue:174`
rgba glows). Only a `dark` theme is defined.

**Do:** collapse to one authoritative token source (Vuetify `variables` if WP5
adopts, else `theme.css`), reference it everywhere, and pull the stray literals
into tokens. Multi-surface codegen (login/email) is **N/A** — no such surfaces.

**Files:** `frontend/src/main.ts`, `styles/theme.css`, offending components.

**Verify:** `grep` for raw hex/rgba in components returns only the token source;
`npm run build`.

### WP7 — Frontend API client seams (P2)

**Kit:** module-vue-vuetify (HTTP client contract).

**Gap:** `frontend/src/api/index.ts` has `ApiError` + `TokenProvider` seam
(good) but no `setUnauthorizedHandler(fn)` global-401 seam, and exposes
`get/post/del` only (no `put`; `del` vs the kit's `delete`). The kit wants the
401 seam present even before auth exists.

**Do:** add `setUnauthorizedHandler` invoked on 401 responses; add `put`, align
`del`→`delete` (keep an alias if needed).

**Files:** `frontend/src/api/index.ts` (+ its test).

**Verify:** `npm run test`; a stubbed 401 triggers the handler.

### WP8 — Notification signal classing (P2)

**Kit:** module-notification-alarm-discipline.

**Gap:** `backend/app/notifications.py` routes actionable gates (`awaiting_*`)
and terminal summaries (`done`, `failed`) into one undifferentiated in-app
list; the UI shows a single unread badge (`NotificationCenter.vue:26`). The kit
separates *actionable alert* from *summary item* and warns against equating
badge count with urgency.

**Do:** tag each notification with a class (e.g. `action_required` vs
`summary`); let `NotificationCenter.vue` separate catch-up items from
action-required gates. Add a forward-looking note: any future push Notifier
(ntfy/webhook/email, `docs/next-steps.md:33`) must pass the kit's
required-properties checklist before it becomes an interrupt channel.

**Files:** `backend/app/notifications.py`,
`frontend/src/components/NotificationCenter.vue`,
`frontend/src/composables/useNotifications.ts`.

**Verify:** `uv run pytest` + `npm run test`; UI shows the two classes
distinctly.

## Deferred (single-user scope)

Each is a real kit deviation, downgraded by the pragmatic bar; revisit if
kestrel ever goes multi-user or is exposed beyond localhost.

- **Rate limiting** (http-middleware-hardening) — localhost single-user; noted
  in WP1's ordering comment.
- **Build-once runtime config** (runtime-config-spa) — the packaged image sets
  `VITE_API_BASE=` empty → same-origin, so one image already serves any
  environment; the kit's runtime-global *mechanism* is absent but the *outcome*
  is met.
- **Release-metadata BuildMeta surface** (release-metadata) — commit SHA /
  build time not exposed in the SPA; a nicety for a single-user tool. Cheap to
  add later (forward `VITE_APP_COMMIT`/`VITE_APP_BUILD_TIME` from the Dockerfile
  + a `BuildMeta.vue` chip) if desired.
- **DB timezone-aware timestamps / request-scoped `get_db`**
  (database-postgresql) — deliberate deviation; documented in WP3 rather than
  changed.
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

## Overall verification

- **Backend:** `cd backend && uv run pytest` green after each backend WP.
- **Frontend:** `cd frontend && npm run test && npm run build` green after each
  frontend WP.
- **Release invariants untouched:** `bash scripts/check_version_sync.sh` still
  passes.
- **Runtime smoke:** build the image (`docker compose build`), start it, and
  `curl` `/livez`, `/readyz`, `/healthz` plus a normal route to confirm headers
  (WP1/WP2).
- **Quality gates:** `pre-commit run --all-files` clean (WP4).
- Each WP ships as its own branch off `master` with a Conventional-Commit
  message and green CI before merge.
