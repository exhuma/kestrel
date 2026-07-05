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
| `text` (default) | Human-readable lines: `timestamp level logger: message` |
| `json` | One JSON document per line |

`KESTREL_LOG_LEVEL` sets verbosity (`debug`, `info`, `warning`, …; default
`info`).

### JSON logs

Set `KESTREL_LOG_FORMAT=json` to emit one JSON document per line, suitable
for ingestion by a log pipeline (OpenTelemetry collectors, Logstash, Loki,
…). Each line has:

```json
{"timestamp":"2026-07-05T11:23:06.320+00:00","level":"INFO","logger":"app.main","message":"Application startup complete."}
```

Exceptions add an `exception` field with the formatted traceback. In
`docker-compose.yml`:

```yaml
environment:
  KESTREL_LOG_FORMAT: json
  KESTREL_LOG_LEVEL: info
```

## Health

`GET /healthz` is a readiness probe: `{"status":"ok","version":"…"}` with
HTTP 200 when ready, HTTP 503 when the database is unreachable. The image and
compose healthchecks use it; see [Configuration → Health and
version](configuration.md#health-and-version).

`GET /api/backends` reports the configured backends and the ad-hoc-session
default — useful to confirm a mounted `backends.toml` took effect.
