# GitHub access for the issue → code workflow

The workflow feature (refine → plan → implement → draft PR) needs a GitHub
personal access token to read/update issues, clone/push, and open PRs. There
is no separate "API key" concept — it's one setting: `DISPATCHER_GITHUB_TOKEN`.

## 1. Create a token

Fine-grained PAT (recommended), scoped to just the test repo:
**github.com → Settings → Developer settings → Personal access tokens → Fine-grained tokens**

Required repository permissions:
- **Contents**: Read and write (push the branch)
- **Issues**: Read and write (read the issue, PATCH it with the refined text)
- **Pull requests**: Read and write (open the draft PR)

A classic PAT with the `repo` scope also works for a quick throwaway test.

## 2. Configure the backend

Settings live in `backend/app/config.py`, env-prefixed `DISPATCHER_`. From
`backend/.env.example`:

```
DISPATCHER_GITHUB_TOKEN=
DISPATCHER_GITHUB_API_BASE=https://api.github.com
DISPATCHER_GIT_BASE=https://github.com
```

**Option A — `.env` file** (persists across restarts):

```bash
cd backend
cp .env.example .env
# edit .env, set:
DISPATCHER_GITHUB_TOKEN=ghp_your_token_here
```

**Option B — inline env var** for a one-off run:

```bash
DISPATCHER_GITHUB_TOKEN=ghp_your_token_here \
DISPATCHER_WORKSPACE_ROOT=/tmp/dispatcher-ws \
uv run uvicorn app.main:app --port 8001
```

`DISPATCHER_GITHUB_API_BASE` and `DISPATCHER_GIT_BASE` default to github.com
and rarely need changing (only for GitHub Enterprise). `GIT_BASE` is used to
build the clone URL as `{git_base}/{owner}/{repo}.git`.

## 3. Run it

Start the frontend against the backend port, e.g.:

```bash
VITE_API_BASE=http://localhost:8001 npm run dev
```

Open the **Workflows** tab, enter `owner/repo` and an issue number, click
**Start workflow**.

Note: this was the first workflow run against a *real* GitHub repo — every
prior test used a mocked `httpx` transport or a local bare git repo (see
`docs/superpowers/specs/2026-07-01-github-issue-workflow-design.md`). Watch
the backend logs for the first live run in case anything about the real
API's response shape differs from what the mocked tests assumed.
