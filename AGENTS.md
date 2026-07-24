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

## Code-quality guardrails

Structural limits are mechanically enforced (they fight module bloat, parameter/
branch creep, and copy-paste). Run everything with one command:

```
task quality
```

**`task quality` must pass before any task is considered done.** It runs, across
Python and JS/TS/Vue: ruff (complexity/bugbear/pylint-derived counts), pylint
(module length ≤ 500), vulture + knip (dead code), import-linter + dependency-
cruiser (layering + no import cycles), eslint (file/function size, complexity,
SonarJS), and jscpd (copy-paste ≤ 3%). Agents also get per-file feedback at edit
time: a `PostToolUse` hook (`tools/agent-check.sh`) runs the relevant checks on
each edited file and blocks on a violation.

The enforced limits (per function/module unless noted):

| Limit | Value | Limit | Value |
| --- | --- | --- | --- |
| cyclomatic complexity | 10 | function arguments | 5 |
| branches | 12 | statements | 40 |
| returns | 5 | locals | 15 |
| module length | 500 lines | function length (JS) | 60 lines |
| nesting depth (JS) | 4 | nested callbacks (JS) | 3 |
| cognitive complexity (JS) | 15 | copy-paste | 3% |

**These are hard constraints.** When you hit one, **split the module or extract a
function/composable** — do not make the check pass by:

- adding `# noqa`, `# pylint: disable`, `eslint-disable`, or `# type: ignore`;
- editing the threshold config (Ruff/ESLint limits, `tools/agent-check.sh`) or
  the grandfather list;
- raising a limit.

If a limit genuinely seems wrong for a case, **stop and ask the developer** —
do not decide unilaterally.

**Grandfathered code.** Files that already exceeded the limits when the harness
was introduced carry narrow exemptions (Ruff `per-file-ignores`, ESLint
`overrides`, a `# pylint: disable=too-many-lines` header) each marked
`TODO(quality): refactor`. This is a shrinking debt list, not a template: new
files get no exemptions, and you must never add entries to it to pass a check.

**Changing a limit (escape hatch).** The threshold config and grandfather list
are guarded in CI (`guard-quality-config`). If a change to them is genuinely
warranted after discussing with the developer, add a line reading
`[quality-override]` to a commit message on the branch (and explain why in the
body). Without it, CI fails any edit to those files.

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
