# Deploying on Kubernetes

This guide runs kestrel on a Kubernetes cluster for a multi-stakeholder
walk-through on Jira Cloud: one pod, three containers, one authenticated
entry point. It is written for the operator. It shows the pieces as inline
YAML to adapt; there are no manifest files in the repository on purpose.

Read [Configuration](configuration.md) and
[Jira workflow](setup-jira-workflow.md) for what each setting means. This
page only says how to wire them up in a cluster.

## What you get

```
                      Ingress (TLS)  kestrel.example.com
                            |
                      Service :4180
 +--------------------------|-------------- one pod, replicas: 1 ---+
 |                          v                                        |
 |  oauth2-proxy  --(X-Forwarded-User/-Email/-Preferred-Username)--> |
 |   :4180 (the only exposed port)                                   |
 |                          |                                        |
 |                          v  http://127.0.0.1:8000                 |
 |  kestrel  (KESTREL_HOST=127.0.0.1)                                |
 |       |   \                                                       |
 |       |    +--> http://localhost:4096  opencode serve (sidecar)   |
 |       v                                                           |
 |   /data (PVC)  /workspaces (PVC, shared with opencode)            |
 +-------------------------------------------------------------------+
        kestrel -> Jira Cloud (poll), code host (git push), IdP (proxy)
```

The shape follows from the constitution's access model: the API is
unauthenticated and meant to be loopback-only. Kestrel binds `127.0.0.1`
inside the pod, so nothing reaches it except the other containers of the
same pod. The only exposed port belongs to oauth2-proxy, which signs people
in against your company identity provider (IdP) first.

Three things to know before you start:

- **Everyone who signs in can do everything.** Kestrel is single-user. It
  reads the identity headers the proxy sets, but it does not tell people
  apart or restrict them. Whoever the IdP lets through is an operator. This
  is an accepted gap, tracked as epic #81. Limit who may sign in at the IdP.
- **Kestrel trusts the identity headers.** It reads `X-Forwarded-User`,
  `X-Forwarded-Email` and `X-Forwarded-Preferred-Username` without checking
  them. The proxy must be the only way in. Never expose port 8000, and do not
  add a second Service or Ingress that points past the proxy.
- **One replica, never two.** State is SQLite and the ingestion, comment and
  recovery loops run inside the process. A second replica would post every
  comment to Jira twice. Use `replicas: 1` and `strategy: Recreate`.

## Prerequisites

- A cluster with an Ingress controller, a default StorageClass that supports
  `ReadWriteOnce` volumes, and a way to get TLS for the external host name.
- DNS for the external URL, for example `kestrel.example.com`.
- An OIDC client at your IdP, with redirect URL
  `https://kestrel.example.com/oauth2/callback`. Note the issuer URL, the
  client id and the client secret.
- A Jira Cloud API token and the account's email address (see
  [Jira account](#the-jira-account) below), the Jira group whose members may
  create ingestible tickets, and the custom field ids for the change owner
  and (optionally) the repository.
- A code-host token that can clone and push to the target repositories
  (GitHub: see [GitHub access](setup-github-workflow.md#1-create-a-token) for
  the permissions; GitLab: `read_repository`, `write_repository`, `api`).
- A model-provider key for opencode (for example an Anthropic API key).
- An image for the opencode sidecar. See [The opencode
  sidecar](#container-2-the-opencode-sidecar).
- An immutable kestrel image tag, for example
  `ghcr.io/exhuma/kestrel:2026.10.5-alpha.1`. Pin a version rather than the
  moving `alpha` channel (see [Releasing](releasing.md)).

## Secrets

Everything secret lives in one Kubernetes Secret, referenced by environment
variable. Nothing secret goes in the ConfigMap.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: kestrel
type: Opaque
stringData:
  KESTREL_JIRA_API_TOKEN: "<jira api token>"
  KESTREL_GITHUB_TOKEN: "<code host token>"      # see the note below
  OPENCODE_SERVER_PASSWORD: "<long random string>"
  OAUTH2_PROXY_CLIENT_SECRET: "<idp client secret>"
  OAUTH2_PROXY_COOKIE_SECRET: "<32 random bytes, url-safe base64>"
  ANTHROPIC_API_KEY: "<model provider key>"       # for opencode only
```

- Generate the cookie secret with
  `python3 -c 'import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'`.
- `KESTREL_GITHUB_TOKEN` is the code-host token when the Jira source says
  `code_host = "github"`. For GitLab or Gitea use `KESTREL_CODE_HOST_TOKEN`
  (or the name you give in `code_host_token_env`). A source's Jira token can
  also be renamed with `token_env`.
- `OPENCODE_SERVER_PASSWORD` is shared: the opencode sidecar uses it to
  protect its server, and kestrel's backend reads it through `api_key_env`.
- The model-provider key belongs to opencode's environment only, never to
  kestrel's. The variable name depends on the provider; `ANTHROPIC_API_KEY`
  is the usual one for Anthropic. Check opencode's provider documentation for
  yours.
- There is no webhook secret: Jira is poll-only and kestrel exposes no
  inbound endpoint besides the UI behind the proxy.

## Storage

Two `ReadWriteOnce` claims. `/data` holds the SQLite database, the board's
handoff artifacts (`/data/board-artifacts`, set by the image) and the
container `HOME`. `/workspaces` holds the bare mirrors, git worktrees and
session directories, and is shared with the opencode sidecar.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: kestrel-data
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 5Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: kestrel-workspaces
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 20Gi
```

Use two claims rather than one claim with `subPath`s: kubelet creates a
`subPath` directory owned by root, which uid 1000 then cannot write. With two
whole volumes, `fsGroup` fixes the ownership for you. Both claims are mounted
by one pod, so they bind to the same node; that is fine for a single replica.

## The ConfigMap

Backend routing and the Jira source are file-only settings
([Configuration](configuration.md#task-sources)). This is a complete MVP
example for Jira Cloud. Replace the placeholders.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: kestrel-config
data:
  config.toml: |
    poll_interval_seconds = 300

    # How kestrel recognises its own comments. It posts as the token's
    # account, so this MUST stay on: with it off no ticket reply is read.
    comment_sentinel_enabled = true
    # A reply must contain this word for kestrel to act on it.
    feedback_marker = "@kestrel"

    # Ad-hoc sessions and every specialist with model_policy = "default".
    # Set this before the first [[backends]] table.
    default_session_backend = "oc"

    [[task_sources]]
    type = "jira"
    base_url = "https://<site>.atlassian.net"
    deployment = "cloud"                  # REST v3 and ADF
    auth = "basic"                        # Cloud: email + API token
    email = "<account email>"
    key = "<PROJECT>"
    jql = '''project = <PROJECT> AND creator in membersOf("DTN_COSS") AND status = "Ready for kestrel" ORDER BY created ASC'''
    repo_field = "customfield_<repo field id>"   # holds owner/name[@branch]
    # or leave repo_field out and put a web link titled "Repository" on the
    # ticket (repo_link_text changes the title)
    change_owner_field = "customfield_<change owner id>"   # a user field
    code_host = "github"                  # github | gitlab | gitea
    # token_env = "KESTREL_JIRA_API_TOKEN"   # defaults, shown for clarity
    # code_host_token_env = "KESTREL_GITHUB_TOKEN"

    [[backends]]
    id = "oc"
    type = "opencode"
    base_url = "http://localhost:4096"
    model = "anthropic/claude-sonnet-4"   # provider/model, as opencode names it
    api_key_env = "OPENCODE_SERVER_PASSWORD"
    allowed_tools = ["read", "grep", "glob", "list", "bash", "edit", "todowrite"]
```

Notes on the file:

- `public_base_url` is **not** a config-file key. Set it with the
  `KESTREL_PUBLIC_BASE_URL` environment variable (below). It is the external
  URL, and it builds the link that ends every comment kestrel posts on a
  ticket. Left empty, comments carry no link.
- Find the custom field ids with Jira's field list (`GET
  /rest/api/3/field`, look for the field names); they look like
  `customfield_10050`. The change owner field must be a **user picker**.
- `key` only scopes dismissals; it is not part of the query.
- The Jira poll uses one interval for every source (`poll_interval_seconds`).
  Kestrel reads ticket replies every 60 seconds by default
  (`board_comment_poll_interval_seconds`).
- The `claude_cli` backend is left out on purpose: the cluster image has no
  Claude login. With only the opencode backend declared, every specialist
  (their `model_policy` is `"default"`) runs on it.
- The config is read once at start. After editing the ConfigMap run
  `kubectl rollout restart deployment/kestrel`.

### Which tickets kestrel ingests

The JQL is the **only** gate on what gets ingested. Whatever it matches is
taken up as a request (after its content passes the input-security
screening, which is a second line of defence, not an authorisation).
For a walk-through with trusted authors, gate on the creator:

```
project = <PROJECT> AND creator in membersOf("DTN_COSS")
  AND status = "Ready for kestrel" ORDER BY created ASC
```

(Written as one line in the file.) `DTN_COSS` is a Jira **group**; adapt the
group, project and status.

- Use `creator`, not `reporter`. The creator is who created the ticket and
  cannot be edited afterwards. The reporter can be changed by anyone who may
  edit the ticket, so gating on it would let an author hand a ticket over
  to a trusted name.
- The reporter is still the person who decides the understanding and PRD
  gates, and the change owner decides CAB-1 and CAB-2, in each case by
  replying `@kestrel ...` on the ticket. See [Replying on the
  ticket](setup-jira-workflow.md#replying-on-the-ticket).
- Kestrel never changes a ticket's status. People move the ticket into
  "Ready for kestrel" (which is what makes it match) and out again.
- The account that owns the API token must be allowed to see the group
  membership and the tickets, or the query silently matches fewer tickets.

### The Jira account

Kestrel posts to Jira as the account whose API token it uses. There is no
service account yet; use a dedicated account once your organisation can
provide one. In the meantime the token owner's own replies still work: kestrel
tells its comments from replies by the ownership marker, not by author (see
the "Jira workflow" page). Mentions and notifications of the posted comments
go to the real reporter and change owner.

## The Deployment

One Deployment, three containers. The pod-level settings matter:

- `replicas: 1` and `strategy: Recreate`, so the old pod stops before the new
  one starts. The entrypoint runs the Alembic migrations on **every** start;
  two pods running them (or a new pod migrating while the old one writes)
  would corrupt the database.
- `securityContext` with uid and gid 1000 and `fsGroup: 1000`. The kestrel
  image runs as 1000:1000 already. The opencode sidecar must run as the same
  uid:gid, so files either side creates are writable by the other.
- `enableServiceLinks: false`. Kubernetes otherwise injects service
  environment variables for every Service in the namespace. A Service named
  `kestrel` produces `KESTREL_PORT=tcp://10.x.x.x:4180`, which kestrel reads
  as its port setting and fails to start. Setting `KESTREL_PORT` explicitly,
  as below, is a second guard.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kestrel
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels: {app: kestrel}
  template:
    metadata:
      labels: {app: kestrel}
    spec:
      enableServiceLinks: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
      volumes:
        - name: data
          persistentVolumeClaim: {claimName: kestrel-data}
        - name: workspaces
          persistentVolumeClaim: {claimName: kestrel-workspaces}
        - name: config
          configMap: {name: kestrel-config}
        - name: opencode-home
          emptyDir: {}
      containers:
        # ... the three containers below ...
```

### Container 1: kestrel

```yaml
        - name: kestrel
          image: ghcr.io/exhuma/kestrel:<tag>
          env:
            - {name: KESTREL_HOST, value: "127.0.0.1"}
            - {name: KESTREL_PORT, value: "8000"}
            - {name: KESTREL_CONFIG_FILE, value: /config/config.toml}
            - {name: KESTREL_PUBLIC_BASE_URL, value: "https://kestrel.example.com"}
            - {name: KESTREL_LOG_FORMAT, value: json}
            - name: KESTREL_JIRA_API_TOKEN
              valueFrom: {secretKeyRef: {name: kestrel, key: KESTREL_JIRA_API_TOKEN}}
            - name: KESTREL_GITHUB_TOKEN
              valueFrom: {secretKeyRef: {name: kestrel, key: KESTREL_GITHUB_TOKEN}}
            - name: OPENCODE_SERVER_PASSWORD
              valueFrom: {secretKeyRef: {name: kestrel, key: OPENCODE_SERVER_PASSWORD}}
          volumeMounts:
            - {name: data, mountPath: /data}
            - {name: workspaces, mountPath: /workspaces}
            - {name: config, mountPath: /config, readOnly: true}
          startupProbe:
            exec:
              command:
                - python
                - -c
                - "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=4).status==200 else 1)"
            periodSeconds: 5
            timeoutSeconds: 6
            failureThreshold: 60
          readinessProbe:
            exec:
              command:
                - python
                - -c
                - "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=4).status==200 else 1)"
            periodSeconds: 30
            timeoutSeconds: 6
          livenessProbe:
            exec:
              command:
                - python
                - -c
                - "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/livez', timeout=4).status==200 else 1)"
            periodSeconds: 30
            timeoutSeconds: 6
            failureThreshold: 3
```

Why exec probes: kubelet's `httpGet` connects to the pod IP, and kestrel
listens on loopback only, so it cannot be reached that way. The probes run
Python inside the container against `127.0.0.1`, the same approach as the
image's `HEALTHCHECK`. A 503 from `/readyz` (database unreachable) raises in
`urlopen` and fails the probe. Python's startup alone takes a moment, so keep
`timeoutSeconds` above the default of one second.

The startup probe gives the entrypoint time to run the migrations. Do not
point `livenessProbe` at `/readyz`: a database hiccup would then restart the
pod; `/livez` only says the process is up.

The entrypoint prints `no Claude config seed mounted` on every start. With
only the opencode backend that warning is harmless.

### Container 2: the opencode sidecar

Kestrel talks to `opencode serve` over HTTP at `http://localhost:4096`, which
works because containers of one pod share a network namespace. The sidecar
must:

- mount the **same volume at the same absolute path** `/workspaces`. Kestrel
  passes absolute paths to opencode, and git worktrees hold absolute `gitdir`
  paths, so a different mount path breaks every worktree;
- run as the **same uid:gid** (1000:1000, from the pod `securityContext`);
- have `git` installed;
- listen on loopback only, protected by `OPENCODE_SERVER_PASSWORD`;
- carry the model-provider credentials in its own environment.

It does not need a code-host token: kestrel does the cloning and pushing.
It does not need the `/data` volume either.

**Check this:** this repository does not publish an opencode image and
documents only `opencode serve --port 4096` (see
[Backends](backends.md#opencode)). Build or choose an image that contains the
opencode CLI, `git` and CA certificates, and check opencode's own
documentation for the bind-address flag (the default is expected to be
loopback; confirm it, and set it explicitly if there is a flag for it) and
for which environment variable your provider reads.

```yaml
        - name: opencode
          image: registry.example.com/opencode:<tag>   # placeholder, see above
          command: ["opencode", "serve", "--port", "4096"]
          workingDir: /workspaces
          env:
            - {name: HOME, value: /home/opencode}
            - name: OPENCODE_SERVER_PASSWORD
              valueFrom: {secretKeyRef: {name: kestrel, key: OPENCODE_SERVER_PASSWORD}}
            - name: ANTHROPIC_API_KEY
              valueFrom: {secretKeyRef: {name: kestrel, key: ANTHROPIC_API_KEY}}
          volumeMounts:
            - {name: workspaces, mountPath: /workspaces}
            - {name: opencode-home, mountPath: /home/opencode}
```

The `emptyDir` for opencode's own state is lost when the pod restarts;
kestrel owns the board state, so that is acceptable. Use a claim instead if
you want opencode's session history to survive.

Kestrel answers opencode's permission prompts itself, so a headless server
never waits for a human. It also auto-approves `bash` in the workspace: only
point it at repositories and tickets you trust (see the security note in
[Backends](backends.md#opencode)).

### Container 3: oauth2-proxy

```yaml
        - name: oauth2-proxy
          image: quay.io/oauth2-proxy/oauth2-proxy:<version>
          args:
            - --provider=oidc
            - --oidc-issuer-url=https://idp.example.com/realms/<realm>
            - --client-id=<client id>
            - --redirect-url=https://kestrel.example.com/oauth2/callback
            - --upstream=http://127.0.0.1:8000
            - --http-address=0.0.0.0:4180
            - --email-domain=example.com
            - --cookie-secure=true
            - --reverse-proxy=true
            - --pass-user-headers=true
            - --skip-provider-button=true
          env:
            - name: OAUTH2_PROXY_CLIENT_SECRET
              valueFrom: {secretKeyRef: {name: kestrel, key: OAUTH2_PROXY_CLIENT_SECRET}}
            - name: OAUTH2_PROXY_COOKIE_SECRET
              valueFrom: {secretKeyRef: {name: kestrel, key: OAUTH2_PROXY_COOKIE_SECRET}}
          ports:
            - {name: http, containerPort: 4180}
          readinessProbe:
            httpGet: {path: /ping, port: 4180}
          livenessProbe:
            httpGet: {path: /ping, port: 4180}
```

- The upstream is `http://127.0.0.1:8000`, kestrel's loopback port. Do not
  add any other route or `--skip-auth-*` option: every request, including
  the API, must be authenticated.
- The headers kestrel reads are `X-Forwarded-User`, `X-Forwarded-Email` and
  `X-Forwarded-Preferred-Username`. `--pass-user-headers` is the default
  that sends the first two, and the third needs a `preferred_username` claim
  from the IdP. **Check this** against the oauth2-proxy version you run;
  the flag names and defaults have changed between releases. Verify in
  [Verify the proxy headers](#verify-the-proxy-headers).
- Restrict who may sign in. `--email-domain` is only the coarsest option;
  prefer assigning the client to specific users or groups at the IdP, or use
  oauth2-proxy's group options. Everyone who passes is a full operator.
- `--reverse-proxy=true` makes the proxy trust the `X-Forwarded-*` headers
  of the Ingress controller (for the redirect URL and client address).
- The pinned `<version>` is yours to choose; use a current release.

## Service and Ingress

Only oauth2-proxy's port is exposed.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: kestrel
spec:
  selector: {app: kestrel}
  ports:
    - {name: http, port: 80, targetPort: 4180}
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: kestrel
  annotations:
    # The UI streams live state over server-sent events: no buffering and a
    # long read timeout. Annotation names are for ingress-nginx; adapt them
    # for another controller.
    nginx.ingress.kubernetes.io/proxy-buffering: "off"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
spec:
  ingressClassName: nginx
  tls:
    - hosts: [kestrel.example.com]
      secretName: kestrel-tls
  rules:
    - host: kestrel.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: kestrel
                port: {number: 80}
```

## First start

Apply the Secret, claims, ConfigMap, Deployment, Service and Ingress, then
watch the pod come up:

```bash
kubectl rollout status deployment/kestrel
kubectl logs deployment/kestrel -c kestrel --tail=100
```

Things to look for in the kestrel log:

- Alembic output ending in a successful `upgrade head`. It runs on every
  start; a start with nothing to apply is quiet.
- `loading config file: /config/config.toml`. If it is missing, the
  ConfigMap is not mounted or `KESTREL_CONFIG_FILE` is wrong, and the pod
  exits with `config_file not found`.
- The effective backends line (`backends: … | ad-hoc sessions dispatch to:
  …`) naming `oc`.
- No warning like `jira task source … has no token`.
- `FATAL: … is not writable by uid 1000:1000` means the volume ownership is
  wrong; see Troubleshooting.

Then dry-run the Jira source. It lists what the JQL matches and the resolved
repositories, and starts nothing:

```bash
kubectl exec deployment/kestrel -c kestrel -- uv run python -m app poll
```

If it lists nothing, test the JQL in Jira's issue search first, as the token
owner.

## Verify

### Health

```bash
kubectl exec deployment/kestrel -c kestrel -- python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/healthz').read().decode())"
kubectl exec deployment/kestrel -c kestrel -- python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health').read().decode())"
```

`/healthz` covers the process and its database. `/api/health` lists each task
source's health (Jira reachable and authenticated), the same indicator the UI
shows. See [Observability](observability.md#health).

### Verify the proxy headers

Sign in at `https://kestrel.example.com`, then open
`https://kestrel.example.com/api/identity`. It should show your username and
email. All fields `null` means the request did not pass through the proxy
or the proxy does not send the headers: stop and fix that before going on.

### The Jira walk-through

Walk a request through every gate with real stakeholders by following
[the 046 quickstart](../specs/046-jira-first-alpha/quickstart.md) (the
manual section against Jira Cloud). In short: move a test ticket that a
trusted creator made into "Ready for kestrel", watch the comment kestrel
posts at each gate, and reply `@kestrel approved` as the reporter and the
change owner in turn.

## Upgrading

1. Back up first (below). Migrations are one-way.
2. Change the image tag in the Deployment and apply it.
3. `Recreate` stops the old pod, then starts the new one, which migrates the
   database on start. Watch `kubectl rollout status` and the log.
4. To roll back, restore the backup **and** set the previous tag. A new
   schema cannot be downgraded.

Change the opencode image and the oauth2-proxy version the same way.

### Backup

Back up `/data`: the SQLite database **and** the board artifacts under
`/data/board-artifacts` belong together. The workspaces can be rebuilt from
the code host and need no backup, but a deleted workspace volume loses
unpushed work.

The most dependable way is a volume snapshot of `kestrel-data` taken with the
pod scaled to zero:

```bash
kubectl scale deployment/kestrel --replicas=0
# create a VolumeSnapshot of PVC kestrel-data (needs a CSI driver with
# snapshot support), then:
kubectl scale deployment/kestrel --replicas=1
```

Without snapshots, a consistent copy of the database while the pod runs is
possible with SQLite's own backup API, followed by copying the file and the
artifacts out:

```bash
kubectl exec deployment/kestrel -c kestrel -- python -c \
  "import sqlite3; s=sqlite3.connect('/data/kestrel.db'); d=sqlite3.connect('/data/kestrel-backup.db'); s.backup(d)"
kubectl exec deployment/kestrel -c kestrel -- \
  tar czf - -C /data kestrel-backup.db board-artifacts > kestrel-data.tgz
```

## Troubleshooting

See also [Troubleshooting](troubleshooting.md).

**The pod crash-loops with `FATAL: … is not writable`.** The volume is not
owned by uid:gid 1000. Check `fsGroup: 1000` is in the pod
`securityContext` and that you did not use `subPath`. Some storage drivers
ignore `fsGroup`; then chown the volume once with an init container.

**Kestrel fails at start with a validation error about `port`.** The
Service-link variable `KESTREL_PORT=tcp://…` leaked in. Set
`enableServiceLinks: false` and `KESTREL_PORT: "8000"`.

**Probes fail but the pod seems fine.** An `httpGet` probe against kestrel
cannot work: it listens on loopback. Use the exec probes above. Also check
`timeoutSeconds`; the default of 1 is too short for a Python process.

**Cards fail with opencode errors, or `401` from opencode.** The password
differs. `OPENCODE_SERVER_PASSWORD` must be the same value in kestrel
(through `api_key_env`) and in the sidecar, and the backend's `username`, if
you set one, must match what the server expects (default `opencode`). The
log of the sidecar shows whether it started: `kubectl logs
deployment/kestrel -c opencode`.

**opencode cannot find the workspace, or git inside it says `not a git
repository` or `dubious ownership`.** The paths or the uid differ. The
sidecar must mount the workspaces volume at `/workspaces` (the same absolute
path as kestrel) and run as 1000:1000.

**Every request through the proxy loops back to sign-in, or gives
`redirect_uri` errors.** `--redirect-url` must equal the redirect URL
registered at the IdP, exactly, and `--cookie-secure=true` needs HTTPS all the
way to the browser (`--reverse-proxy=true` for the Ingress).

**`/api/identity` shows `null` fields.** The request did not carry the
headers. Check the Service targets 4180 (not 8000), and the proxy version's
header options (see the container section).

**The live views freeze or reconnect often.** Buffering or a short timeout
in the Ingress is cutting the event stream. Apply the annotations above or
their equivalent for your controller.

**Comments on the ticket have no link.** `KESTREL_PUBLIC_BASE_URL` is unset.
Note it is an environment variable, not a `config.toml` key.

**Replies on the ticket are ignored.** Check, in this order:

1. `comment_sentinel_enabled` is not `false`. With it off, no reply is read.
2. The reply was written **after** kestrel posted the comment announcing the
   gate. Replies older than the announcement are left alone. If Jira was
   unreachable, the announcement is retried; reply again once it is there.
3. The reply contains the marker (`@kestrel`) as a whole word, and its
   author is entitled to decide: the reporter for the understanding and
   PRD, the change owner for CAB-1 and CAB-2. Anyone else gets a message
   saying so.
4. The clocks. Kestrel compares its own time with Jira's comment times
   without tolerance, so a skewed node clock can make a fresh reply count
   late or not at all. Check the node's time synchronisation.

**Nothing is ingested.** Run `python -m app poll` (see above), test the JQL
in Jira as the token owner, and check the creator really is a member of the
group and the ticket is in the status the JQL names.

**An ingested ticket has no repository.** Kestrel logs it every poll and
posts nothing. Check `repo_field` (or the web link titled by
`repo_link_text`) holds `owner/name`, and that the code-host token can see
the repository.

**Settings changes have no effect.** The config is read once at start:
`kubectl rollout restart deployment/kestrel`.
