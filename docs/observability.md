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
| `text` (default) | Human-readable lines: `timestamp level [trace_id] logger: message` |
| `json` | One JSON document per line |

Log lines are linked to distributed traces by W3C **trace context**, not a
bespoke correlation header. Each record carries `trace_id` / `span_id` fields
taken from the active span (`-` when no span is in flight — startup, shutdown,
background work, or with tracing disabled). Enable [Tracing](#tracing) to
populate them and to correlate a request across services.

`KESTREL_LOG_LEVEL` sets verbosity (`debug`, `info`, `warning`, …; default
`info`).

### JSON logs

Set `KESTREL_LOG_FORMAT=json` to emit one JSON document per line, suitable
for ingestion by a log pipeline (OpenTelemetry collectors, Logstash, Loki,
…). Each line has:

```json
{"timestamp":"2026-07-05T11:23:06.320+00:00","level":"INFO","logger":"app.main","message":"Application startup complete."}
```

`trace_id` (and `span_id`) fields are added to records emitted while a span is
active (tracing enabled). Agent records add `session_id` and `card_id` (see
[Agent output](#agent-output)). Exceptions add an `exception` field with the
formatted traceback. In `docker-compose.yml`:

```yaml
environment:
  KESTREL_LOG_FORMAT: json
  KESTREL_LOG_LEVEL: info
```

### Agent output

Kestrel stores nothing of what an agent did: no transcript, no events. The
server log is the only record, written through one logger, `kestrel.agent`,
for every backend (Claude CLI, opencode). Each record carries the backend's
**session id** and, when the turn works for a board card, the **card id** —
in the message (`session=<id> card=<id> …`) and, with
`KESTREL_LOG_FORMAT=json`, as `session_id` / `card_id` fields.

| Level | What is logged |
| --- | --- |
| `INFO` | A session started or resumed; the turn's result (length-limited) |
| `WARNING` | An error result, or a turn that ended without one (crash, timeout, stop) |
| `DEBUG` | Every event of the turn: assistant text, tool calls and results, reasoning |

Free text is cut to 500 characters per line, so a log line stays small
however much the agent wrote. `DEBUG` also lowers the level for everything
else; set `KESTREL_LOG_LEVEL=debug` to read a turn step by step, and filter on
the session id.

To find the output of one card attempt:

1. The attempt row (`board_card_attempt`) stores the session id as soon as the
   backend reports it, even if the turn later fails:

   ```sql
   SELECT sequence, backend_id, session_id, status
   FROM board_card_attempt WHERE card_id = '<card id>' ORDER BY sequence;
   ```

2. Filter the log by it: `docker compose logs kestrel | grep 'session=<id>'`,
   or select `session_id = "<id>"` in a JSON log pipeline. A card can also be
   followed by `card_id` across its attempts.

## Tracing

Kestrel can emit **OpenTelemetry** distributed traces. Tracing is **off by
default** — a single-user localhost tool needs no collector — and is a clean
no-op until enabled, so it costs nothing when unused. It follows
`module-opentelemetry`: spans and W3C trace-context only; the OpenTelemetry SDK
is confined to one facade module (`app/telemetry.py`) so the vendor stays
swappable.

Enable it by setting `KESTREL_OTEL_ENABLED=true` and pointing the standard
`OTEL_*` environment variables at a collector:

```yaml
environment:
  KESTREL_OTEL_ENABLED: "true"
  OTEL_EXPORTER_OTLP_ENDPOINT: http://collector:4318   # OTLP/HTTP
  OTEL_TRACES_SAMPLER_ARG: "1.0"                        # head sample ratio
```

When enabled, kestrel auto-instruments FastAPI (server spans on every request)
and the logging module (so `trace_id` / `span_id` populate the log fields
above), and exports spans over OTLP/HTTP with parent-based ratio sampling. All
endpoint, sampling, and resource settings come from the standard `OTEL_*`
variables.

Application **metrics** (a Prometheus/VictoriaMetrics `/metrics` endpoint) are
deliberately not shipped — see `module-observability-metrics` and
`docs/qm-alignment.md`. The OTLP metrics exporter is disabled
(`OTEL_METRICS_EXPORTER=none`) so nothing is pushed by the wrong path.

For production you may instead run under the zero-code agent, which builds the
tracer provider from `OTEL_*` with no in-process setup:

```bash
opentelemetry-instrument python -m app
```

## Health

Kestrel exposes three probes. Each returns a compact JSON body — `probe`,
`status` (`ok` / `degraded` / `fail` / `unknown`), `checked_at`, and a
`components` list — and never leaks the running version, connection strings, or
error text. The version is reported separately in the `X-Kestrel-Version`
response header. Each dependency check is bounded by a timeout; a check that
overruns reports `unknown` (unconfirmed, not proven dead) rather than `fail`.

| Probe | Checks | 200 when | 503 when |
| --- | --- | --- | --- |
| `GET /livez` | Process is up; no dependencies | always | never |
| `GET /readyz` | Required dependencies (the database) | ready | a required dependency fails or is unknown |
| `GET /healthz` | Summary of required + optional dependencies | ok / degraded | a required dependency fails |

```json
{"probe":"readyz","status":"ok","checked_at":"2026-07-05T11:23:06+00:00","components":[{"name":"database","kind":"database","required":true,"status":"ok","reason_code":"ok","latency_ms":0}]}
```

Use `/livez` for restart decisions and `/readyz` for traffic gating. The image
and compose healthchecks call `/readyz` so an instance whose database is
unreachable is gated out rather than served; see [Configuration → Health and
version](configuration.md#health-and-version).

### Task-source and code-host health

The status icon in the top bar shows each configured source (Jira, GitHub,
the GitLab or Gitea code host) as healthy or unreachable, re-checked every
`health_check_interval_seconds`. The UI deliberately shows no cause. The
cause goes to the server log at WARNING, with the traceback, when a source
becomes unreachable or its reason changes:

```text
WARNING  kestrel.health: health: jira unreachable: ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] ...
INFO     kestrel.health: health: jira reachable again
```

The same failure repeated on later checks is logged at DEBUG only, so the log
is not flooded. Search for `health:` to find these lines. With JSON logging
the traceback is in the `exception` field.
