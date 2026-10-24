# Research: Validated LLM Output

## Decision: Retry only required artifacts

Required artifact failures must not use text fallbacks because those fallbacks
can silently cross an approval or execution boundary. Optional enrichment and
reconciliation retain current deterministic fallbacks.

**Rationale**: Required output gates progress or creates work. Optional output
does neither, or it has a known-good prior value to retain.

**Alternatives considered**: Retrying every model request would add cost and
latency for optional diagnostics without increasing workflow correctness.

## Decision: Five total attempts through one helper

The first normal request is attempt one; at most four correction requests are
sent after validation failures. The helper returns a typed validated result or
raises a concise error after the final failure.

**Rationale**: The user selected five total calls. A shared helper gives every
required boundary the same stop condition and correction wording.

**Alternatives considered**: Persisting retry counters is unnecessary because a
restart during an active model request already fails the transient run.

## Decision: Preserve valid verifier rejections

A valid rejection verdict remains evidence and consumes a normal verify round.
Only malformed or absent verdict output is retried.

**Rationale**: Retrying evidence-based rejection would hide a real defect;
retrying a format failure only recovers model output conformance.
