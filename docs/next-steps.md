# Next steps

Status as of 2026-07-15: **first alpha shipped.** The MVP workflow (GitHub
issue → refine → clarify → plan → implement → draft PR, with human approval
gates and pause/resume at every stage) is complete, persisted, and verified
end-to-end against real GitHub issues and PRs. Kestrel is packaged as a
CalVer-tagged Docker image (`Dockerfile`, `docker-compose.yml`,
`.github/workflows/release.yml`).

**The backlog now lives in the
[GitHub issue tracker](https://github.com/exhuma/kestrel/issues).** The local
plan/spec history (`docs/superpowers/`) was removed in favour of issues; the
milestones it tracked (M-A, M-B, M-D, M-E, M-F, M-G) are all delivered and the
remaining work was filed as issues.

## Where the outstanding work is tracked

- **[#20 · M-C GitHub ingestion & repo ops](https://github.com/exhuma/kestrel/issues/20)**
  — webhook ingress (HMAC + dedup), poll reconciliation, per-run `git worktree`
  isolation. The largest remaining feature; turns kestrel from "click to start
  a run" into "notices new/updated issues on its own."
- **Optional / on-demand back-ends** —
  [#21 access gate](https://github.com/exhuma/kestrel/issues/21),
  [#22 more Notifier back-ends](https://github.com/exhuma/kestrel/issues/22),
  [#23 Planka source](https://github.com/exhuma/kestrel/issues/23),
  [#24 Zammad source](https://github.com/exhuma/kestrel/issues/24).
- **[#25 · Retry/resume path for a failed run](https://github.com/exhuma/kestrel/issues/25)**
  — the state machine has no in-place transition to re-enter a `failed` run.
- **[#26 · DX / demo polish](https://github.com/exhuma/kestrel/issues/26)**
  — dev-server defaults and the >500 kB bundle-size warning.
- **[#27 · Small contained backend/UI fixes](https://github.com/exhuma/kestrel/issues/27)**
  — a checklist of quick, safe-to-defer cleanups.

Deferred, single-user-scope kit deviations (application metrics, live trace
collector, rate limiting, etc.) remain recorded in
[`qm-alignment.md`](qm-alignment.md); the metrics item is tracked on
[#17](https://github.com/exhuma/kestrel/issues/17).

## Explicitly out of scope (by design, not gaps)

- **Multi-user / auth** — single-user by design; the access gate (#21) is the
  only planned protection, and it's explicitly *not* multi-user auth.
- **Auto-merging the PR** — the workflow opens a draft PR only; merging is a
  manual human action on GitHub (the review gate, by design).
- **Incremental commits during implement** — the implement step makes one
  commit at the end, not as the agent works.
