# Agent-Dispatcher — Feasibility Spike Design

**Date:** 2026-06-30
**Status:** Approved
**Scope:** Feasibility spike (de-risk the core mechanic only)

## Context

We are investigating an autonomous **agent-dispatcher**: a long-running
service that spawns coding-agent sessions to run development tasks with
human-in-the-loop handovers (e.g. GitHub issue refinement; plan → human
review → implement). This document covers only the **first iteration**, a
feasibility spike.

This is a **personal, single-user** coding assistant. That matters for two
reasons:

1. It keeps us in Anthropic's "ordinary, individual usage" lane for running
   the `claude` CLI under a **Max subscription** (flat-rate, not per-token).
   Multi-user / productized use would require an API key under Commercial
   Terms — explicitly out of scope.
2. It justifies the spike's simplifications: in-memory state, no auth, single
   concurrent user.

### Worker-agent decision

The dispatcher **shells out to the real `claude -p` binary** as a subprocess,
authenticated via the machine's logged-in Max plan (OAuth). We deliberately do
**not** embed the Claude Agent SDK or reuse OAuth tokens in our own harness —
Anthropic banned that path (Feb 2026); it requires an API key. Spawning the
official CLI is the only path that honors the "subscription, not tokens"
requirement.

## Goal

De-risk the one mechanic everything else depends on: *a long-running
dispatcher can spawn a Claude Code session, watch it live in a browser, then
resume that exact session with new human input.* This is Chain 2's
"plan → human revises → resume same session" loop in miniature.

## Architecture

```
Browser (Vue/Vuetify)  ──REST──>  FastAPI dispatcher  ──asyncio subprocess──>  `claude -p`
        ^                              │                                          (Max OAuth)
        └──────── SSE (live events) ───┘   parses stream-json stdout (JSONL)
```

Stack baseline: Quartermaster `stack-fastapi-vuetify` (FastAPI backend +
Vue/Vuetify frontend), loaded at implementation time.

### Backend components

- **`SessionRunner`** — spawns
  `claude -p "<prompt>" --output-format stream-json --verbose` via
  `asyncio.create_subprocess_exec`, reads stdout line-by-line, parses each JSON
  event, and extracts `session_id` from the init/system event. Resume is the
  same invocation with `--resume <id>`. Runs in a fixed working directory so
  resume can locate the session.
- **In-memory session registry** — `{session_id: {status, cwd, events[]}}`. No
  database (spike).
- **REST + SSE endpoints**
  - `POST /sessions` — start a new session with a prompt → returns `session_id`
  - `POST /sessions/{id}/resume` — resume with new human input
  - `GET /sessions` — list sessions
  - `GET /sessions/{id}/events` — SSE live stream of parsed events
  - New events fan out to SSE subscribers as they arrive.

### Frontend

One Vuetify page: a session list, a Start control, a live event-log panel
(SSE-subscribed), and a "resume" text box to send follow-up input to a selected
session.

## The hard-coded happy path (the demo that proves it)

1. **Start**: prompt = *"Write a haiku about the sea into `poem.txt`."* → watch
   tool calls + result stream into the browser; capture `session_id`.
2. **Resume**: send *"Now revise it to be about mountains instead."* to that
   `session_id` → confirm it edits the **same file** using prior context,
   proving session continuity/resume across separate subprocess invocations.

## Unknowns the spike resolves

- Exact `stream-json` event shape and where `session_id` first appears.
- The right **non-interactive permission mode** so unattended runs don't block
  on approval prompts (likely `--permission-mode acceptEdits`, run in a
  throwaway dir).
- That resume works **across separate processes** given a matching cwd.
- That it all runs under the **Max subscription** (logged-in `claude`, no
  `ANTHROPIC_API_KEY` set).

## Out of scope

Real GitHub / webhooks, durable persistence, auth, error recovery & retries,
concurrency limits, the formal two chains, multi-user. In-memory, single-user,
happy-path only.

## Success criteria

- [ ] Start a session and see events stream live in the browser.
- [ ] Capture its `session_id`.
- [ ] Resume that exact session and observe it acting on prior context.
- [ ] Confirmed running on the Max subscription (no API key set).

## Spike results (2026-06-30)

**Verdict: feasibility confirmed.** All success criteria met via a live
run against the real `claude` CLI on the host (driven through the Vue UI
in a real browser).

### Success criteria
- [x] Start a session and see events stream into the browser — the live
  log rendered all 14 events of the first run (`hook_started`, `init`,
  `thinking_tokens`, `assistant`, `user`/tool_result, `result:success`),
  0 console errors.
- [x] Capture the `session_id` — surfaced from the first stream event;
  session shown in the UI list (`73ce55fc-… · idle`).
- [x] Resume that exact session — same `session_id`, event count grew
  14 -> 23, still a single session; `poem.txt` was revised in place from
  a sea haiku to a mountains haiku, proving cross-process continuity with
  prior context.
- [x] Subscription billing — `apiKeySource: "none"`,
  `overageStatus: "rejected"` (`org_level_disabled`): ran on the Max
  subscription with API overage disabled (cannot silently fall back to
  token billing). No `ANTHROPIC_API_KEY` set.

### Resolved unknowns
- **stream-json shape**: `session_id` is present from the very first
  event; events carry top-level `type` (`system`/`assistant`/`user`/
  `result`/`rate_limit_event`) with `system` events sub-typed
  (`hook_started`, `init`, `thinking_tokens`, ...). Run ends with a
  single `type:"result"` event. The parser's tolerant "type + optional
  session_id + raw" model handled every variant.
- **Permission mode**: `--permission-mode acceptEdits` ran fully
  non-interactively (Write/Edit auto-accepted), 0 `permission_denials`,
  in a throwaway per-session workdir.
- **Cross-process resume**: confirmed working given a stable per-session
  cwd (`--resume <id>` in the same directory).

### Bugs found by the e2e (fixed during verification)
1. **SSE/​frontend contract mismatch** — the events endpoint sent the
   bare `ev.raw` dict, but the frontend `SessionEvent`/template expected
   `{type, session_id, raw}`, so `JSON.stringify(e.raw)` was `undefined`
   and threw on every event. Fixed `_sse` to emit the full shape; added
   a regression test. (Each side passed its own task review; only the
   cross-file integration surfaced it.)
2. **CORS** — origin was hard-pinned to `localhost:5173`; relaxed to any
   `localhost:<port>` (5173 was occupied by another local app).

### Known limitations (deferred, see ledger)
- Blocking start/resume: events appear after the run completes (then SSE
  replays), not token-by-token. True incremental streaming needs an
  `on_id` early-return upgrade (also closes the stream_events
  snapshot-before-subscribe gap).
