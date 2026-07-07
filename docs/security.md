# Security model & hardening

Kestrel takes an **untrusted GitHub issue** and runs it through an AI-agent
pipeline (refine → plan → implement → draft PR). The issue text is embedded
into agent prompts, and the `implement` step runs a coding agent that can
edit files, execute shell commands, and make network requests. Treat every
issue body and comment as attacker-controlled input: a malicious issue is a
**prompt injection**, and a successful injection can drive the agent to run
arbitrary commands or make arbitrary requests.

This document describes the threat model, the controls kestrel ships, and the
operator responsibilities that the software cannot enforce on its own.

## Threat model

**Trust boundary.** Everything from GitHub (issue title, body, comments) is
untrusted. Kestrel's own code, its configuration, and the secrets it holds
(the GitHub token, the agent's Claude credentials) are trusted and must stay
on the trusted side of the boundary.

**Two attack vectors** we defend against:

1. **Shell-command execution.** An injection convinces the agent to run
   destructive or exfiltrating shell commands (the agent legitimately has a
   Bash tool during `implement`).
2. **Web / API requests.** An injection convinces the agent — or kestrel
   itself via a poisoned backend response — to make malicious outbound
   requests: SSRF against internal services, exfiltration of secrets or
   source, or abuse of the GitHub token to damage repositories through the
   API.

**Backend asymmetry.** Sandboxing (below) applies only to the local
`claude_cli` backend, the one that spawns a subprocess on the kestrel host.
The `opencode` and `openai_compat` backends run the agent **off-host** over
HTTP; kestrel cannot sandbox a process it does not spawn. Those backends are
constrained by the egress allowlist and by your trust in the remote host that
runs them — run them somewhere you would be comfortable running untrusted
agent output.

## Controls kestrel ships

### API access gate

Every `/api/*` route is gated behind a single shared-secret bearer token,
`KESTREL_API_TOKEN`. When it is set, requests must present
`Authorization: Bearer <token>` (or, for SSE `EventSource` clients that cannot
set headers, an `access_token` query parameter). When it is **unset**, the API
is open, and the server refuses to bind a non-loopback interface — an open API
may only ever listen on `127.0.0.1`. To bind `0.0.0.0` without a token (for
example inside a container whose host publishes the port to loopback only),
set `KESTREL_ALLOW_INSECURE_BIND=1` to assert that isolation explicitly.

This is a single shared secret, not multi-user authentication.

### Input validation

The `repo` field of a workflow request is validated at the API boundary
against a strict `owner/repo` slug pattern. This rejects leading dashes
(argument injection into `git clone` and REST paths), `..` (path traversal),
whitespace and control characters, and URL-shaped values. `git clone` is
additionally invoked with a `--` separator as defense-in-depth.

### Refinement-skip integrity

An issue whose body carries a kestrel "already refined" marker skips the
refinement stage and proceeds straight to planning. That marker is an HMAC
signed with `KESTREL_SENTINEL_SECRET` over the refined text, so only text
kestrel itself produced can skip refinement. An attacker who types the marker
string into a raw issue — or edits signed text after the fact — fails the
signature check and gets a normal refinement pass. With no secret configured,
markers are never trusted and every run re-refines.

### Bounded error surface

GitHub error responses are truncated before they reach `run.error` and the
logs, so a large or sensitive upstream error page cannot leak in full. The
GitHub token is only ever sent in a request header (never a URL or body) and
is redacted from git command errors.

### Egress allowlist (default-deny)

An optional compose overlay (`docker-compose.egress.yml`) puts kestrel on an
**internal network with no route to the internet** and forces all of its
outbound traffic through an allowlist forward-proxy (squid). Only the hosts
kestrel actually needs are reachable; everything else fails closed at the
network layer, so a prompt injection cannot exfiltrate data or reach internal
services (SSRF) even if it convinces the agent to try.

The allowlist is **derived from kestrel's own configuration** — the git and
GitHub-API hosts, the Anthropic API host, and every configured backend URL —
by `app.services.egress`, so it never drifts from what the app legitimately
reaches. Add extra hosts (an MCP server, a self-hosted model) with
`KESTREL_EGRESS_ALLOWLIST`. Kestrel logs the effective allowlist at startup.

HTTPS traffic uses `CONNECT`, so the proxy allowlists by hostname without
seeing tunneled bytes; the GitHub token and Anthropic credentials stay
confidential even from the proxy.

Enable it with:

```bash
docker compose -f docker-compose.yml -f docker-compose.egress.yml up
```

Regenerate the proxy ACL after changing backends or bases (the `egress-init`
step does this automatically on each `up`); to preview it:
`python -m app.services.egress -`.

### Per-run sandbox

> Status: see `docs/next-steps.md` for rollout. When enabled, each `claude_cli`
> run executes inside an ephemeral, per-run sandbox (a gVisor-isolated
> container) with all capabilities dropped, a read-only root filesystem, only
> the run's workspace mounted writable, no-new-privileges, and egress routed
> through the allowlist proxy. The GitHub token is **never** placed inside the
> sandbox: kestrel performs the single controlled push and PR from trusted
> host-side code, so a compromised agent cannot push directly or exfiltrate
> the token.

### Container hardening

The shipped image runs as an unprivileged user (uid 10001), not root. The
provided `docker-compose.yml` publishes the port to host loopback only, mounts
the root filesystem read-only, drops all Linux capabilities, sets
`no-new-privileges`, and applies memory / PID / CPU ceilings.

## Operator responsibilities

The software cannot enforce these — they are yours.

### Run only in an isolated environment

Kestrel executes untrusted-driven agent code. Run it on a **dedicated,
disposable host or VM** that you are willing to have compromised — never on a
workstation with access to unrelated secrets, credentials, or internal
networks. Keep the API on loopback (or behind `KESTREL_API_TOKEN`).

### Scope the GitHub token to least privilege

The token can push branches and mutate issues and PRs on every repo it can
reach, so a prompt injection that reaches the token's capabilities can damage
those repos through the API. Reduce the blast radius:

- Use a **fine-grained PAT scoped to exactly the target repository** (or a
  single throwaway repo for testing) — not an org-wide or classic `repo`
  token.
- Grant only the minimum: **Contents R/W**, **Issues R/W**, **Pull requests
  R/W**. Nothing else.
- Enable **branch protection** on the target repo requiring review before
  merge. Kestrel opens **draft** PRs and never merges, so a human stays in the
  loop; branch protection makes that a hard guarantee even if the token is
  abused.

See `docs/setup-github-workflow.md` for the step-by-step token setup.

### Protect the agent's Claude credentials

The agent authenticates with the host's Claude login, seeded read-only into
the container. Those credentials are a high-value exfiltration target. Prefer
a **dedicated, least-privilege Anthropic API key** over your personal
subscription OAuth token, so that a leak is scoped and independently
revocable. The egress allowlist limits where credentials can be sent, but
scoping the credential itself is the stronger control.

### Filesystem ownership

The container runs as uid 10001. A host bind mount for `/workspaces` must be
writable by that uid (`sudo chown 10001 workspaces`), or use a named volume.

## Reporting

This is a personal-scale alpha tool. If you find a security issue, open an
issue describing the impact and reproduction (without a working exploit
payload against third-party infrastructure).
