# GitHub access for the issue → code workflow

The workflow feature (refine → plan → implement → draft PR) needs a GitHub
personal access token to read/update issues, clone/push, and open PRs. There
is no separate "API key" concept — it's one setting: `KESTREL_GITHUB_TOKEN`.

## 1. Create a token

Fine-grained PAT (recommended), scoped to just the test repo. On
**github.com**, open **Settings → Developer settings → Personal access
tokens → Fine-grained tokens**.

Required repository permissions:
- **Contents**: Read and write (push the branch)
- **Issues**: Read and write (read the issue, PATCH it with the refined text)
- **Pull requests**: Read and write (open the draft PR)

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

## 3. Run it

Open the **Workflows** tab, enter `owner/repo` and an issue number, and click
**Start workflow**.

## 4. Automatic ingestion (optional)

Instead of entering an issue by hand, kestrel can start a run when you apply a
label to an issue on GitHub, and catch up on any it missed. This is additive —
the manual **Start workflow** path keeps working.

### Configure

| Variable | Required | Purpose | Default |
| --- | --- | --- | --- |
| `KESTREL_WEBHOOK_SECRET` | Yes | HMAC shared secret verifying deliveries. Empty disables the webhook path | _(empty)_ |
| `KESTREL_WATCHED_REPOS` | Yes | Allow-list of `owner/name` repos, comma-separated or a JSON array | _(empty)_ |
| `KESTREL_TRIGGER_LABEL` | No | The label that flags an issue | `kestrel` |
| `KESTREL_RECONCILE_INTERVAL_SECONDS` | No | How often to poll for missed deliveries | `300` |
| `KESTREL_PUBLIC_BASE_URL` | No | Public URL of the kestrel UI, used to make gate-notification links clickable | _(empty)_ |

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
- **Events**: select **Issues** (kestrel handles `labeled` to start a run and
  `unlabeled` to clear a dismissal).

### Use it

Apply the `kestrel` label to an issue in a watched repo. A run starts on its
own and appears in the **Workflows** tab. Abandoning a run dismisses that issue
so it is not re-ingested while the label remains; remove and re-add the label to
run it again. Deliveries missed while kestrel was offline are picked up on the
next reconciliation cycle.
