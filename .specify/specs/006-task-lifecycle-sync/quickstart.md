# Quickstart: validating task-source lifecycle sync, time tracking, and hooks

This is a validation guide for once the feature is implemented (see `tasks.md` for the
build steps). It does not duplicate the wire format or data model — see
`contracts/hook-wire-format.md` and `data-model.md` for those.

## Prerequisites

- Backend running from source (`uv run fastapi dev` or the project's existing dev
  flow) or the bundled Docker image — either existing run mode works, this feature
  changes neither.
- Migration applied: `alembic upgrade head` (adds the new `workflow_run` columns —
  migration `0012_run_lifecycle_time.py`).
- At least one configured `[[task_sources]]` entry in `config.toml` — a GitHub source
  is the simplest to validate against without a Jira instance.
- A GitHub repo/issue kestrel is already configured to watch (existing setup, see
  `docs/setup-github-workflow.md`).

## 1. Automated tests (fast path — run this first)

```bash
cd backend
uv run pytest tests/test_active_time.py tests/test_lifecycle_transitioner.py \
  tests/test_hooks.py tests/test_github_ports.py tests/test_jira_ports.py -v
```

Expected: all pass, including the exhaustive `kind`-mapping invariant test (a
failed/escalated/rejected run's `LifecycleEvent` is never `kind="done"`) and the
env-inheritance regression test (hook subprocess spawn receives no `env=` override).

```bash
uv run alembic upgrade head   # against a fresh SQLite test DB
```

Expected: succeeds; pre-existing `workflow_run` rows now read `active_seconds=0.0`,
`wait_seconds=0.0`, `clock_state=NULL`, `clock_since=NULL`.

## 2. Manual end-to-end: status sync + time tracking (no hooks yet)

1. In `config.toml`, on the GitHub `[[task_sources]]` entry, leave `hooks_dir` unset
   and confirm `in_progress_label`/`failed_label`/etc. are at their defaults (or set
   your own).
2. Trigger a run against a real (or sandboxed) GitHub issue kestrel watches.
3. **Expect**: within a short time, the issue gets the `kestrel-in-progress` label.
4. Let the run pause at least once for your input/approval (a refine gate) — wait a
   deliberate amount of time (e.g. 2 minutes) before responding.
5. Approve/respond, let the run complete successfully (opens a PR).
6. **Expect**: the `kestrel-in-progress` label is removed; a comment footer appears on
   the issue reporting active time and wait time (GitHub has no native time field, so
   both go to the footer per FR-006) — the wait-time figure should approximate your
   deliberate pause from step 4, and active time should exclude it.
7. Trigger a second run and force it to fail (e.g. an unrecoverable error, or reject
   the PRD at the approval gate).
8. **Expect**: the ticket never shows a "done" signal — the in-progress label is
   removed and a distinct failure-terminal label (`kestrel-rejected` or
   `kestrel-failed`) is applied instead.

## 3. Manual end-to-end: hooks

1. Create a hooks directory and a trivial script:

   ```bash
   mkdir -p /tmp/kestrel-hooks-demo
   cat > /tmp/kestrel-hooks-demo/00-dump.sh <<'EOF'
   #!/bin/sh
   cat > "/tmp/kestrel-hook-$$-$(date +%s).json"
   env | grep -i KESTREL > "/tmp/kestrel-hook-env-$$.txt"
   EOF
   chmod +x /tmp/kestrel-hooks-demo/00-dump.sh
   ```

2. Set `hooks_dir = "/tmp/kestrel-hooks-demo"` on the GitHub `[[task_sources]]` entry
   and restart kestrel.
3. **Expect** (startup audit log, FR-016): kestrel's startup logs mention
   `00-dump.sh` was found in the configured hooks directory.
4. Trigger a run against a watched issue through to completion.
5. **Expect**: a `/tmp/kestrel-hook-*.json` file appears — inspect it against
   `contracts/hook-wire-format.md`'s stdin schema table (event kind, run id, task
   ref, active/wait seconds, links). A `/tmp/kestrel-hook-env-*.txt` file appears
   containing `KESTREL_GITHUB_TOKEN` (or whichever token env var is configured) —
   confirms the intentional full-environment inheritance (FR-011).
6. **Expect**: kestrel's own label transition and footer comment from step 2 above
   still happen exactly as before — the hook is additive, not a replacement (FR-009).
7. Replace the script with one that sleeps 60s (`sleep 60; exit 0`), trigger another
   run.
8. **Expect**: the run's own lifecycle handling (label, footer) is not delayed by 60s
   — the hook is killed at the 30s mark (FR-010) and kestrel's logs note the timeout;
   the run itself is unaffected.

## Cleanup

```bash
rm -rf /tmp/kestrel-hooks-demo /tmp/kestrel-hook-*
```

Remove `hooks_dir` from `config.toml` (or point it elsewhere) once validation is done.
