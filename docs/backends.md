# Backends (experimental)

Kestrel dispatches to a pluggable **backend**. By default the only backend is
the bundled `claude` CLI, so no configuration is needed. To add backends
(self-hosted LLMs, opencode), write a **TOML file** and point kestrel at it:

```bash
KESTREL_CONFIG_FILE=config.toml   # relative to the working dir, or absolute
```

Copy [`config.toml.example`](../config.toml.example) to `config.toml` and
edit. Alongside the applicative settings (see
[Configuration](configuration.md)), it declares the available backends and
the ad-hoc-session default:

```toml
default_session_backend = "local"

[[backends]]
id = "claude"
type = "claude_cli"

[[backends]]
id = "local"
type = "openai_compat"    # a self-hosted OpenAI-compatible LLM
base_url = "http://localhost:11434/v1"
model = "llama3.1:8b"
```

Per-**specialist** routing — which backend a given board role (`coder`,
`verifier`, `requester`, `pm`, …) dispatches to — is not set in
`config.toml`. It is each role's `model_policy` field in its own
`specialists/<role>/manifest.toml` (see
[Architecture → The work board](architecture.md#the-work-board-spec-026)):
`"default"`
resolves to `default_session_backend` above; any other value names a
specific `[[backends]]` id directly, e.g.:

```toml
# specialists/coder/manifest.toml
model_policy = "claude"   # the coder needs file-editing, so pin it explicitly
```

Config is read once at startup — **restart the backend after editing it**. On
boot the effective config is logged (`backends: … | ad-hoc sessions dispatch
to: …`), and `GET /api/backends` reports it live. In Docker, mount the file
and set the env var (see the commented lines in `docker-compose.yml`).

> The TOML file is the **only** way to configure backends. Without
> `KESTREL_CONFIG_FILE` set, kestrel runs claude-only.

## Reaching a backend from the Docker container

The `base_url` examples use `localhost`, which is correct when you run kestrel
**from source**. Inside the container, however, `localhost` is the container
itself — a backend running on the Docker host is **not** reachable at
`localhost`.

From the published image, use one of:

- `http://host.docker.internal:PORT` — the Docker host as seen from the
  container. The published `docker-compose.yml` already maps
  `host.docker.internal` to the host gateway, so this works out of the box.
- A **compose service name**, if you run the backend as another service on
  the same compose network (address it as `http://service-name:PORT`).

So a host-run Ollama that you'd reach at `http://localhost:11434/v1` from
source becomes `http://host.docker.internal:11434/v1` in `config.toml` when
running the image.

## Where backends apply

Ad-hoc sessions (the **Sessions** debug panel / `POST /api/sessions`) use
`default_session_backend`. Every board specialist (`requester`, `pm`,
`uiux`, `developer`, `infosec`, `dba`, `architect`, `ops`, `qa`,
`coordinator`, `coder`, `verifier`, `input-security`) uses its own
manifest's `model_policy` — `"default"` for the same default, or a pinned
backend id.

A specialist only accepts a backend that satisfies its `required_abilities`:
`coder` needs file-editing (`claude`/`opencode`), since it is the only role
that holds a repository write lease, while most other roles need only text
— so a plain LLM may serve them (it just won't read the repo). A bad mapping
(e.g. a text-only LLM pinned to `coder`) fails capability-checked routing
(`SpecialistBackendPolicy.backend_for`) with a clear error rather than
silently dispatching anyway.

## Concurrency and rate limits

Every configured backend has a process-wide concurrency cap. It is shared by
every specialist dispatch and ad-hoc session using that backend ID, not
reset per board workflow. The conservative default is one in-flight LLM
turn. Backends have independent caps, so a busy local backend does not
delay a Claude backend.

```toml
[[backends]]
id = "azure-opencode"
type = "opencode"
base_url = "http://host.docker.internal:4096"
model = "azure/gpt-5"
max_concurrency = 1
rate_limit_retries = 3
rate_limit_backoff_seconds = 2.0
```

`max_concurrency` must be a positive integer. Raise it only after confirming
the provider quota can absorb concurrent calls. The cap applies inside one
kestrel process; multiple kestrel processes each enforce their own cap.

For `opencode`, HTTP 429 responses retry up to `rate_limit_retries` times. A
positive `Retry-After` header is honored; otherwise retries use exponential
backoff from `rate_limit_backoff_seconds` with jitter. Other error responses
are not retried by this policy. `rate_limit_retries` must be zero or greater,
and `rate_limit_backoff_seconds` must be positive.

## Backend types

### `claude_cli`

The bundled Claude Code CLI. This is the default and needs no fields beyond
`id` and `type`.

### `openai_compat`

A self-hosted OpenAI-compatible LLM (Ollama, vLLM, LocalAI, …). It is
**text-only** (no file edits or tools); kestrel owns the conversation history
and replays it each turn.

```toml
[[backends]]
id = "local"
type = "openai_compat"
base_url = "http://host.docker.internal:11434/v1"   # localhost from source
model = "llama3.1:8b"
# api_key = "sk-…"        # or api_key_env = "MY_LLM_KEY" (an exported env var)
# timeout = 300           # seconds; raise for big/slow models
```

### `opencode`

A full file-editing agent reached over
[`opencode serve`](https://opencode.ai/docs/server/). Start the server
separately (`opencode serve --port 4096`), point `base_url` at it, and set
`model` as `provider/model`:

```toml
[[backends]]
id = "oc"
type = "opencode"
base_url = "http://host.docker.internal:4096"   # localhost from source
model = "anthropic/claude-sonnet-4"
```

For a **secured** server (one started with `OPENCODE_SERVER_PASSWORD`), give
the password so kestrel can send HTTP Basic auth (username defaults to
`opencode`; override with `username`). Put it inline via `password` — the
config file is gitignored — or, to keep it out of the file, use `api_key_env`
naming an env var you **export** in kestrel's process:

```toml
[[backends]]
id = "oc"
type = "opencode"
base_url = "http://host.docker.internal:4096"
model = "opencode/deepseek-v4-flash-free"
password = "changeme"                      # inline (gitignored file), or:
# api_key_env = "OPENCODE_SERVER_PASSWORD"  # name of an exported env var
```

> **opencode working directory.** Each request kestrel sends is scoped to the
> session's working directory (the per-run cloned workspace, or an ad-hoc
> session's own folder) via opencode's `directory` parameter, so opencode's
> file tools act there rather than in the directory where `opencode serve` was
> started. The `opencode serve` process must be able to reach that path — run
> it on the same host/mount as kestrel's `KESTREL_WORKSPACE_ROOT`.
>
> **opencode read-only specialists and permissions.** A specialist whose
> manifest declares `workspace_permission = "read_only"` (or `"none"`) runs
> read-only: kestrel disables opencode's file-mutating tools
> (`edit`/`write`/`patch`) for its turns and rejects any edit permission the
> agent still asks for, so it can read and run commands but cannot change the
> workspace. Only `coder` (`workspace_permission = "write"`) runs with edits
> enabled. kestrel answers opencode's
> permission prompts itself — it streams the server's `/event` bus and replies
> to each request — so a headless `opencode serve` never blocks waiting for a
> human to click "allow"; you do **not** need to pre-configure opencode's
> permissions. An auto-started `serve` supervisor is still in progress.
>
> **Tools and runaway turns (feature 036).** Every tool your opencode server
> offers is available to kestrel's turns by default, including the MCP servers
> in your opencode config (GitLab, Jira, …). No kestrel specialist needs those:
> the ticket is already in its prompt. List the tools a backend may use and
> everything else is hidden from the model:
>
> ```toml
> allowed_tools = ["read", "grep", "glob", "list", "bash", "edit", "todowrite"]
> max_repeated_tool_calls = 5   # same tool, same input: abort the turn
> max_tool_calls = 150          # total tool calls per turn: abort the turn
> ```
>
> Names are opencode's own, and wildcards work (`"gitlab_*"`). opencode checks
> `write` and `apply_patch` under `edit`, so list `edit` to allow any file
> change. Read-only turns stay read-only whatever the list says.
>
> **Allowing an MCP server.** opencode names an MCP server's tools
> `<server>_<tool>`, where `<server>` is the server's key in *your opencode
> config* (not anything kestrel defines). A server registered as
> `"playwright"` offers `playwright_browser_navigate`,
> `playwright_browser_click`, and so on. Allow the whole server with a
> wildcard, or only some of its tools by name:
>
> ```toml
> # every tool of the "playwright" MCP server
> allowed_tools = ["read", "grep", "glob", "list", "bash", "edit", "todowrite",
>                  "playwright_*"]
> # or just two of them
> # allowed_tools = [..., "playwright_browser_navigate",
> #                  "playwright_browser_take_screenshot"]
> ```
>
> kestrel only allows or hides what the opencode server already offers: the
> MCP server itself must be configured in opencode. Without `allowed_tools`
> every MCP tool is available already, so the entry matters only once you
> set an allowlist. MCP tools are not file-writing tools, so read-only turns
> can use them too. Browser-driving turns make many calls; raise
> `max_tool_calls` if they hit the budget.
> `allowed_tools` is rejected on other backend types. Both limits apply with
> or without an allowlist. A stopped turn fails like any other: the request
> says why, naming the tool, and recovery retries it. While a turn runs, the
> request's activity line shows the tool being called and how many calls the
> turn has made.
>
> **Security (alpha).** To run unattended, kestrel auto-approves opencode's
> tool use — including `bash` inside the workspace. A prompt-injected
> repository or issue could therefore get the agent to run arbitrary shell
> commands in the cloned workspace. This risk applies to the other file-editing
> backends too; hardening it (sandboxing, command allow-lists) is deferred.
> Only point kestrel at repositories and issues you trust.
