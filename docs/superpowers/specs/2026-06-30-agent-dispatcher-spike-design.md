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
