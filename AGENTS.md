# kestrel

Personal, single-user tool that dispatches and monitors coding-agent sessions
(Claude Code CLI, opencode, or a self-hosted LLM) from a web UI. FastAPI backend
+ Vue 3 / Vuetify frontend.

## Governance & specs — read before changing code

- **Constitution** — non-negotiable principles and binding constraints:
  `.specify/memory/constitution.md`
- **Baseline spec** — current behavior, as built: `.specify/specs/000-baseline/`
- **Architecture** — system context: `docs/architecture.md`

The constitution overrides convenience; when it and this file disagree, it wins.

## Workflow

- **For any non-trivial feature or behavior change, start with
  `/speckit.specify` before writing code.** Trivial fixes may skip it.

## Quartermaster (instruction kits)

Quartermaster is an MCP server that serves versioned, on-demand *instruction
kits* — agent guidance for specific stacks and capabilities. Kit content is
loaded-on-demand context for the current session only; it is never copied into
this repo.

- **Start every task with `resolve_kits(task="…")`** — per task, not once per
  project. It ranks matching kits and inlines each kit's `always_load` sections.
- **Pull extra sections on demand** with `get_kit(name, sections=[…])`; don't
  load everything upfront.
- **Re-run `resolve_kits` when the task's direction shifts** and new traits come
  into scope (e.g. "add authentication" resolving to OIDC mid-discussion).
- **Never hard-code a fixed kit list here** — a static list loads too much or too
  little; the traits a task touches often only emerge during the work.
