"""OpenTelemetry telemetry facade for kestrel.

This is the **only** module that imports OpenTelemetry, per
``module-opentelemetry`` (v2). Application code depends on this narrow port
(:func:`span`, :func:`record_exception`) and never touches the SDK, so the
tracing vendor is swappable by re-implementing this one file.

Tracing is **disabled by default** and is a clean no-op when off: with no
tracer provider installed the OpenTelemetry API returns a no-op tracer, so
call sites work unchanged whether or not telemetry is configured. Enable it by
setting ``KESTREL_OTEL_ENABLED=true`` and the standard ``OTEL_*`` environment
variables (at least ``OTEL_EXPORTER_OTLP_ENDPOINT``); see
:func:`init_tracing`.

This kit owns traces and W3C trace-context only. Application metrics
(``/metrics``, Prometheus/VictoriaMetrics) are owned by
``module-observability-metrics`` and are intentionally not wired here — kestrel
is a single-user localhost tool with no scrape infrastructure.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

from opentelemetry import trace

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI

    from app.config import Settings

_logger = logging.getLogger(__name__)

#: One tracer for the whole app. Resolves to a no-op tracer until (and unless)
#: :func:`init_tracing` installs a provider.
_tracer = trace.get_tracer("kestrel")


@contextmanager
def span(name: str, **attributes: object) -> Iterator[trace.Span]:
    """Open a manual span named ``name`` with optional attributes.

    A no-op when telemetry is disabled. Use for domain operations the
    auto-instrumentation cannot infer.
    """
    with _tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            current.set_attribute(key, value)
        yield current


def record_exception(exc: Exception) -> None:
    """Record ``exc`` on the current span and mark the span status ERROR."""
    current = trace.get_current_span()
    current.record_exception(exc)
    current.set_status(trace.Status(trace.StatusCode.ERROR))


def init_tracing(app: FastAPI, settings: Settings) -> None:
    """Wire OpenTelemetry tracing at the composition root.

    A no-op unless ``settings.otel_enabled``. When enabled, install a
    parent-based ratio-sampled tracer provider that exports spans over OTLP
    (endpoint and sampling ratio read from the standard ``OTEL_*`` environment
    variables), then auto-instrument FastAPI and the logging module so log
    records carry ``trace_id`` / ``span_id`` linked to the active span.

    :param app: The FastAPI application to instrument.
    :param settings: Runtime settings; ``otel_enabled`` gates all wiring.
    """
    if not settings.otel_enabled:
        _logger.debug("OpenTelemetry tracing disabled (KESTREL_OTEL_ENABLED)")
        return

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import (
        ParentBased,
        TraceIdRatioBased,
    )

    # Application metrics use the pull model (module-observability-metrics),
    # not OTLP push; silence the auto-instrumentation's metrics exporter unless
    # the operator has deliberately overridden it.
    os.environ.setdefault("OTEL_METRICS_EXPORTER", "none")

    ratio = _sampling_ratio()
    resource = Resource.create(
        {"service.name": settings.otel_service_name or "kestrel"}
    )
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(ratio)),
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    global _tracer
    _tracer = trace.get_tracer("kestrel")

    FastAPIInstrumentor.instrument_app(app)
    # set_logging_format=False: kestrel owns its log format (JsonFormatter);
    # the instrumentation only enriches records with otelTraceID/otelSpanID.
    LoggingInstrumentor().instrument(set_logging_format=False)
    _logger.info(
        "OpenTelemetry tracing enabled (service=%s, sample_ratio=%.3f)",
        resource.attributes.get("service.name"),
        ratio,
    )


def _sampling_ratio() -> float:
    """Head sampling ratio from ``OTEL_TRACES_SAMPLER_ARG`` (default 1.0).

    Parent-based sampling keeps a trace whole; this ratio is the root
    decision. Sample near 1.0 in dev/low-traffic; lower it under load.
    """
    raw = os.environ.get("OTEL_TRACES_SAMPLER_ARG", "1.0")
    try:
        return min(1.0, max(0.0, float(raw)))
    except ValueError:
        return 1.0
