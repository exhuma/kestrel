# GitHub access for the issue → board workflow

Watching a GitHub repository for board work needs a GitHub personal access
token to read/update issues and clone/push. There is no separate "API key"
concept — it's one setting: `KESTREL_GITHUB_TOKEN`.

## Marking kestrel's own comments

Kestrel appends `[kestrel:posted]` to every comment it posts by default, so
a future consumer of comment history can tell a kestrel-authored comment
from a human one. (The old fixed driver's `@kestrel approve` /
`@kestrel reject` / `@kestrel request changes` feedback pipeline, which also
used this marker to avoid reacting to its own comments, was removed in the
Phase 10 clean break — see
[Architecture](architecture.md#the-work-board-spec-026) — and currently has
no board-domain replacement, so nothing currently reads ticket comments back
into kestrel.)

Keep `comment_sentinel_enabled = true` in `config.toml` unless the connected
source cannot preserve the marker. Kestrel posts through your account, so the
ownership marker on its comments is how it tells them apart from yours; how
the marker looks is decided by each source adapter (feature 046).

## 1. Create a token

Fine-grained PAT (recommended), scoped to just the test repo. On
**github.com**, open **Settings → Developer settings → Personal access
tokens → Fine-grained tokens**.

Required repository permissions:
- **Contents**: Read and write (clone/push a delivery branch)
- **Issues**: Read and write (read the labeled issue that seeds a board
  workflow; write access is forward-looking for once task-source write-back
  is wired up — see [Architecture](architecture.md#the-work-board-spec-026))
- **Pull requests**: Read and write (forward-looking, same reason — opening
  a change request is not yet automated)

A classic PAT with the `repo` scope also works for a quick throwaway test.

## 2. Configure the token

Set these environment variables on the kestrel service (for the Docker
deployment, the `environment:` block of `docker-compose.yml`):

| Variable | Required | Purpose | Default |
| --- | --- | --- | --- |
| `KESTREL_GITHUB_TOKEN` | Yes | The token from step 1 | _(empty — feature disabled)_ |
| `KESTREL_GITHUB_API_BASE` | No | GitHub REST API base URL; change only for GitHub Enterprise | `https://api.github.com` |
| `KESTREL_GIT_BASE` | No | Base URL for git clones; change only for GitHub Enterprise | `https://github.com` |

These appear in the full settings reference in
[Configuration](configuration.md#environment-variables). Running from source
instead? See [Development](development.md) for the `backend/.env` route.

## 3. Watch a repository

Runs are never started by hand. Kestrel starts one when you apply a label to
an issue in a watched repository, and catches up on any delivery it missed, so
configuring a `github` task source is required rather than optional.

### Configure

The webhook secret and the UI base URL are env vars; the watched repos and
trigger label are a `github` [task source](configuration.md#task-sources) in
`config.toml`.

| Variable | Required | Purpose | Default |
| --- | --- | --- | --- |
| `KESTREL_WEBHOOK_SECRET` | Yes | HMAC shared secret verifying deliveries. Empty disables the webhook path | _(empty)_ |
| `KESTREL_POLL_INTERVAL_SECONDS` | No | How often to reconcile for missed deliveries | `300` |
| `KESTREL_PUBLIC_BASE_URL` | No | Public URL of the kestrel UI, used to build a deep link back to a run | _(empty)_ |

```toml
# config.toml — the repos to watch and the trigger label:
[[task_sources]]
type = "github"
watched_repos = ["owner/name"]   # required allow-list
trigger_label = "kestrel"        # the label that flags an issue
# token_env = "KESTREL_GITHUB_TOKEN"  # optional (default)
```

### Expose the endpoint

The webhook endpoint `POST /api/github/webhook` must be reachable by GitHub.
This is the one endpoint intended to face the network; every other route stays
loopback-bound, and the HMAC signature is its authenticity gate (see the
constitution's access model). How you expose it — a tunnel or a reverse
proxy — is your responsibility.

### Register the webhook

In the repository's **Settings → Webhooks → Add webhook**:

- **Payload URL**: `https://<your-public-host>/api/github/webhook`
- **Content type**: `application/json`
- **Secret**: the same value as `KESTREL_WEBHOOK_SECRET`
- **Events**: select **Issues**. (Older setup instructions also selected
  **Issue comments**, **Pull request reviews**, and **Pull request review
  comments** for the old driver's comment-based feedback pipeline; that
  pipeline was removed in the Phase 10 clean break and the webhook handler
  no longer reads those event types at all, so there's no need to select
  them — see [Architecture](architecture.md#the-work-board-spec-026).)

### Use it

Apply the `kestrel` label to an issue in a watched repo. Kestrel creates a
board workflow for it — after screening the issue body through the
fail-closed input-security quarantine — and it appears on the **Board**.
Deliveries missed while kestrel was offline are picked up on the next
reconciliation cycle. From here, watching progress, resolving any human
gate or quarantined security review, and retrying/cancelling/reassigning a
card all happen **in the Kestrel UI**, not on the GitHub issue — see
[Architecture](architecture.md#the-work-board-spec-026) for what's wired up
today and what (lifecycle labels, comment-based feedback, decomposition
into linked issues) is not yet.
