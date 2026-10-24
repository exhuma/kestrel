# Contract: Per-Backend Concurrency and Rate-Limit Configuration

**Feature**: 025-backend-concurrency-cap

The observable contract of this feature is the `config.toml` surface. No new
HTTP endpoints, CLI flags, or UI elements are introduced.

## Config file contract (`[backends.<id>]`)

All three keys are optional. Absent keys take the defaults below.

```toml
[backends.azure]
type = "opencode"
base_url = "https://example.opencode.local"
model = "gpt-5.4"
max_concurrency = 1            # NEW, int >= 1, default 1
rate_limit_retries = 3         # NEW, int >= 0, default 3
rate_limit_backoff_seconds = 2.0  # NEW, float > 0, default 2.0
```

### Field semantics

| Key | Type | Default | Invalid values | Effect when valid |
|-----|------|---------|----------------|-------------------|
| `max_concurrency` | integer | `1` | `<= 0`, non-integer → startup error naming the field | At most this many in-flight LLM calls for this backend, process-global across all workflow runs and ad-hoc sessions |
| `rate_limit_retries` | integer | `3` | `< 0`, non-integer → startup error | Max retries after a rate-limit (429) rejection on the OpenCode backend; `0` disables retrying |
| `rate_limit_backoff_seconds` | number | `2.0` | `<= 0`, non-numeric → startup error | Base delay (seconds) for exponential backoff when the provider sends no usable `Retry-After` |

### Behavior contract

1. **Cap scope**: global per backend ID within one kestrel process;
   independent across backends. Multiple kestrel processes each apply their
   own cap (documented limitation).
2. **Queueing**: turns beyond the cap wait; waiting is not bounded by any
   turn timeout and is cancellable.
3. **Retry**: only rate-limit rejections are retried, on the OpenCode
   backend. `Retry-After` (positive seconds) is honored when present and
   parseable; otherwise wait = `backoff * 2**(retry-1)` + jitter in
   `[0, backoff/2]`. After `rate_limit_retries` retries the turn fails with
   a diagnostic naming rate limiting.
4. **Backward compatibility**: configs without the new keys behave exactly as
   before, except that the default cap of 1 now serializes turns per backend
   (this is the intended fix).
