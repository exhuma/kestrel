# GitHub access for the issue → code workflow

The workflow feature (refine → plan → implement → draft PR) needs a GitHub
personal access token to read/update issues, clone/push, and open PRs. There
is no separate "API key" concept — it's one setting: `KESTREL_GITHUB_TOKEN`.

## 1. Create a token

Fine-grained PAT (recommended), scoped to just the test repo:
**github.com → Settings → Developer settings → Personal access tokens → Fine-grained tokens**

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
