# Observability

## Logs

Kestrel writes all logs to **stdout** — the container never manages log
files. Collect them with `docker compose logs` or your platform's log
driver.

Both uvicorn's logs and the application's own logs share **one stream and
one format**: the container launches via `python -m app`, which hands a
single logging config to uvicorn so its loggers propagate to the same root
handler. There is no split between "server" and "app" output.

### Format

`KESTREL_LOG_FORMAT` selects the console format:

| Value | Output |
| --- | --- |
| `text` (default) | Human-readable lines: `timestamp level [correlation_id] logger: message` |
| `json` | One JSON document per line |

Every request is tagged with a correlation ID: the backend honours an inbound
`X-Correlation-ID` header or generates one, echoes it on the response, and
stamps it on every log line emitted while that request is in flight (`-` for
startup, shutdown, and background work). This lets you trace one request
across all of its log records.

`KESTREL_LOG_LEVEL` sets verbosity (`debug`, `info`, `warning`, …; default
`info`).

### JSON logs

Set `KESTREL_LOG_FORMAT=json` to emit one JSON document per line, suitable
for ingestion by a log pipeline (OpenTelemetry collectors, Logstash, Loki,
…). Each line has:

```json
{"timestamp":"2026-07-05T11:23:06.320+00:00","level":"INFO","logger":"app.main","message":"Application startup complete."}
```

A `correlation_id` field is added to records emitted while handling a request.
Exceptions add an `exception` field with the formatted traceback. In
`docker-compose.yml`:

```yaml
environment:
  KESTREL_LOG_FORMAT: json
  KESTREL_LOG_LEVEL: info
```

## Health

Kestrel exposes three probes. Each returns a compact JSON body — `probe`,
`status` (`ok` / `degraded` / `fail`), `checked_at`, and a `components` list —
and never leaks the running version, connection strings, or error text. The
version is reported separately in the `X-Kestrel-Version` response header.

| Probe | Checks | 200 when | 503 when |
| --- | --- | --- | --- |
| `GET /livez` | Process is up; no dependencies | always | never |
| `GET /readyz` | Required dependencies (the database) | ready | database unreachable |
| `GET /healthz` | Summary of required + optional dependencies | ok / degraded | a required dependency fails |

```json
{"probe":"readyz","status":"ok","checked_at":"2026-07-05T11:23:06+00:00","components":[{"name":"database","kind":"database","required":true,"status":"ok","reason_code":"ok","latency_ms":0}]}
```

Use `/livez` for restart decisions and `/readyz` for traffic gating. The image
and compose healthchecks call `/readyz` so an instance whose database is
unreachable is gated out rather than served; see [Configuration → Health and
version](configuration.md#health-and-version).

`GET /api/backends` reports the configured backends and the ad-hoc-session
default — useful to confirm a mounted `backends.toml` took effect.
