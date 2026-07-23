# Backends (experimental)

Kestrel dispatches to a pluggable **backend**. By default the only backend is
the bundled `claude` CLI, so no configuration is needed. To add backends
(self-hosted LLMs, opencode), write a **TOML file** and point kestrel at it:

```bash
KESTREL_CONFIG_FILE=config.toml   # relative to the working dir, or absolute
```

Copy [`config.toml.example`](../config.toml.example) to `config.toml` and
edit. Alongside the applicative settings (see
[Configuration](configuration.md)), it declares the available backends, the
ad-hoc-session default, and the per-workflow-step assignments:

```toml
default_session_backend = "local"

[step_backends]           # step -> backend id; omitted steps use the default
implement = "claude"      # keep implement on claude (see the opencode note)

[[backends]]
id = "claude"
type = "claude_cli"

[[backends]]
id = "local"
type = "openai_compat"    # a self-hosted OpenAI-compatible LLM
base_url = "http://localhost:11434/v1"
model = "llama3.1:8b"
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

Ad-hoc sessions (the **Sessions** panel / `POST /api/sessions`) use
`default_session_backend`. Each GitHub-workflow step (`refine`, `plan`,
`implement`) uses its `step_backends` entry if set, else the same default.

A step only accepts a backend that can satisfy it: `implement` needs
file-editing (`claude`/`opencode`), while `refine`/`plan` need only text — so
a plain LLM may serve them (it just won't read the repo). A bad mapping (e.g.
a text-only LLM on `implement`) fails that run with a clear capability error.

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
> **opencode read-only steps and permissions.** The reasoning steps (`refine`,
> `plan`) run read-only: kestrel disables opencode's file-mutating tools
> (`edit`/`write`/`patch`) for those turns and rejects any edit permission the
> agent still asks for, so they can read and run commands but cannot change the
> workspace. `implement` runs with edits enabled. kestrel answers opencode's
> permission prompts itself — it streams the server's `/event` bus and replies
> to each request — so a headless `opencode serve` never blocks waiting for a
> human to click "allow"; you do **not** need to pre-configure opencode's
> permissions. Live activity indicators (thinking / reading / writing, from the
> same `/event` stream) and an auto-started `serve` supervisor are still in
> progress.
>
> **Security (alpha).** To run unattended, kestrel auto-approves opencode's
> tool use — including `bash` inside the workspace. A prompt-injected
> repository or issue could therefore get the agent to run arbitrary shell
> commands in the cloned workspace. This risk applies to the other file-editing
> backends too; hardening it (sandboxing, command allow-lists) is deferred.
> Only point kestrel at repositories and issues you trust.
