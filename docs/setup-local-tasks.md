# Local tasks workflow

Local tasks provide a disposable workflow with no tracker, credentials,
hosted repository, pull request, or code review. Kestrel publishes the delivery
branch to a local bare Git repository instead.

## Configure

The root `config.toml` includes the local source alongside Jira. Its
`tasks_dir` is relative to the backend working directory (`backend/`), so the
example `../.kestrel-local-tasks` resolves to the ignored root directory.

```toml
[[task_sources]]
type = "local"
tasks_dir = "../.kestrel-local-tasks"
code_host = "local"
```

`code_repo` in every local task must be an absolute path to a local bare Git
repository. Kestrel reads its symbolic `HEAD` when `base_branch` is omitted.

## Task folders

Each task is a directory anywhere below `tasks_dir`, identified by its
root-relative path. For example, `frontend/hello/task.json` has reference
`local:frontend/hello`.

```text
.kestrel-local-tasks/frontend/hello/
├── task.json
├── comments/
├── attachments/
└── children/
```

```json
{
  "title": "Add a hello endpoint",
  "body": "Add GET /hello.",
  "code_repo": "/tmp/pyaltiplano.git",
  "base_branch": "master"
}
```

Discovery is recursive and sorted by root-relative path. `task.json` is the
only file that defines a task. Attachments and generated children are written
only in their owner's `attachments/` and `children/` directories.

## Feedback

**Currently dormant**: the file format below is still read by
`LocalTaskSource`, but nothing in the current board domain calls it to
steer a workflow — the old fixed driver's feedback pipeline that consumed
it was removed in the Phase 10 clean break and has no board-domain
replacement yet (see
[Architecture → Current gap](architecture.md#current-gap-no-verification-loop-or-task-source-write-back-yet)).
Use the Kestrel UI to act on a board workflow's cards and gates instead.

Put human feedback in `comments/` as UTF-8 Markdown with a UTC filename:

```text
comments/2026-09-10T14.30.00.md
comments/2026-09-10T14.30.00-malbert.md
```

The optional suffix is a human-readable author or note using letters, numbers,
underscores, and hyphens. Add a numeric suffix for same-second comments. The
timestamp must be current or newer than the prior feedback cursor; use the
`local-tasks:add-comment` helper rather than creating filenames manually.
Kestrel writes replies as `YYYY-MM-DDTHH.MM.SS-kestrel[-N].md` and excludes
those exact filenames, so it never consumes its own feedback.

## Helpers

`task local-tasks:init` creates the ignored example task. Use
`LOCAL_TASK=frontend/hello BODY='@kestrel revise this' task local-tasks:add-comment`
to add human feedback. `local-tasks:list`, `local-tasks:show-task`,
`local-tasks:show-comments`, `local-tasks:branches`, and `local-tasks:reset`
inspect or reset local data. These helpers reject absolute and parent-traversal
task paths.

Set `LOCAL_AUTHOR` to add a sanitized readable suffix, for example
`LOCAL_AUTHOR=malbert` creates a filename ending in `-malbert.md`.

`task local-tasks:reset` removes all local tasks and Kestrel development
persistence: `backend/kestrel.db` (including SQLite sidecars), workspaces, and
screenshots. It does not alter `/tmp/pyaltiplano.git`.

Run the canonical `task dev` command to start the backend and frontend together.

Run `python -m app poll` to preview discovered tasks without starting runs.
Successful delivery posts `Branch published locally: <branch>` to the local task
comments and does not open a change request.
