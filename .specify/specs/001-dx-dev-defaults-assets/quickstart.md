# Quickstart / Validation Guide: DX polish — zero-config dev servers & lighter frontend assets

Runnable checks that prove each user story works end-to-end. Run from the repo
root unless noted. See [research.md](./research.md) for the decisions behind
these and [data-model.md](./data-model.md) for the icon alias registry.

## Prerequisites

- `uv` (backend) and Node/npm (frontend) installed.
- `cd frontend && npm install` (this pulls the new `@mdi/js` and drops
  `@mdi/font` once `package.json` is updated).

## US1 — Zero-config dev servers (P1, hard)

Goal: both dev servers run and the UI reaches the backend with **no env vars and
no `.env`**.

```bash
# Terminal 1 — backend (no flags, no env vars)
cd backend && uv run uvicorn app.main:app --reload      # serves on :8000

# Terminal 2 — frontend (no .env / .env.local present)
cd frontend && npm run dev                               # serves on :5173
```

**Expected**:
- Backend listens on `http://localhost:8000` with no `--port` flag.
- Opening `http://localhost:5173` loads the UI; the Workflows and Sessions views
  populate (network calls go to `http://localhost:8000/...`, not `:5173`).
- No console/network errors caused by a wrong API base.

**Footgun regression check** (the `.env.example` fix): copying the example must
NOT break dev.

```bash
cd frontend && cp .env.example .env.local && npm run dev
```

**Expected**: the UI still reaches `:8000` (because the fixed `.env.example`
leaves `VITE_API_BASE` commented/unset, so the in-code default applies). Then
remove the copy: `rm frontend/.env.local`.

**Override check (FR-004)**:

```bash
cd frontend && echo 'VITE_API_BASE=http://localhost:9999' > .env.local && npm run dev
```

**Expected**: requests target `:9999` (explicit value wins). Clean up
`.env.local` afterwards.

**Docs consistency (SC-002)**: `grep -rn 8001 README.md docs/ backend/README.md`
returns nothing; every port reference is `8000`.

## US2 — Only ship used icons (P2, hard requirement)

```bash
cd frontend && npm run build          # vue-tsc -b && vite build
```

**Expected**:
- Build completes with **no oversized-asset/chunk warning** (SC-004).
- No Material Design Icons **webfont** among emitted assets:
  ```bash
  find frontend/dist -iname '*materialdesignicons*' -o -iname '*.woff2'   # -> no MDI webfont
  ```
- First-load payload materially smaller than the pre-change baseline
  (research.md records ~403 kB woff2 + inflated CSS removed) — **≥50%
  uncompressed reduction** (SC-003). Compare `du -sh` / the Vite build asset
  summary before vs. after.

**Visual parity (SC-005, 100%)**: run `npm run dev` and confirm every icon still
renders — no missing-glyph boxes — across all views, in **both** light and dark
themes (toggle via the app-bar sun/moon button). Spot-check the icon-bearing
surfaces: header status chip + theme toggle (App), the bell + read/unread dots
(NotificationCenter), rocket/close/alert/arrow icons (WorkflowPanel), rocket/
close/radar (SessionPanel), cog/subdirectory/code-json (EventCard).

**Automated guard**: `cd frontend && npm test` — the icons spec asserts every
`mdi-*` name used in `src/` resolves to a non-empty SVG path (data-model.md
validation rule); the api spec asserts `API_BASE` default resolution.

## US3 — On-demand panel code (P3, optional/best-effort)

Only if code-splitting was implemented:

```bash
cd frontend && npm run build
# Inspect emitted chunks: the default (workflows) entry should not include the
# sessions panel's code; switching views should fetch a separate chunk.
```

**Expected (target, not a gate — SC-006)**: separate chunks for the two panels;
opening the non-default view fetches its chunk on demand and renders, with a
loading indicator if not instantaneous and a clear error if the fetch fails
(FR-009). If US3 was not implemented, this section is skipped and does not block
completion.

## Definition of Done (gate summary)

- [ ] US1 dev servers run zero-config; `.env.example` copy does not break dev;
      explicit override works; docs all say 8000.
- [ ] US2 build has no webfont, no size warning, ≥50% payload reduction, 100%
      icon parity in both themes.
- [ ] `npm test` (frontend) and `uv run pytest` (backend) pass; formatters clean.
- [ ] (Optional) US3 chunks split with loading/error affordances.
- [ ] Docs updated where behaviour/setup is described (README, docs/, backend
      README, `.env.example`).
