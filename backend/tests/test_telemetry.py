"""Tests for the OpenTelemetry telemetry facade.

Asserts at the facade boundary with an in-memory span exporter — no live
collector — per module-opentelemetry. The facade is swapped onto a test
tracer via monkeypatch so the global tracer provider stays untouched and the
tests remain isolated.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from app import telemetry


@pytest.fixture
def exporter(monkeypatch) -> InMemorySpanExporter:
    """Point the facade at a fresh in-memory-exporting tracer."""
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    monkeypatch.setattr(telemetry, "_tracer", provider.get_tracer("kestrel"))
    return exp


def test_span_is_recorded_with_attributes(exporter) -> None:
    """Ensure telemetry.span opens a named span carrying its attributes."""
    with telemetry.span("unit.work", phase="test"):
        pass
    spans = exporter.get_finished_spans()
    match = next(s for s in spans if s.name == "unit.work")
    assert match.attributes["phase"] == "test"


def test_record_exception_marks_span_error(exporter) -> None:
    """Ensure record_exception sets ERROR status and records the event."""
    with telemetry.span("op"):
        telemetry.record_exception(ValueError("boom"))
    span = next(s for s in exporter.get_finished_spans() if s.name == "op")
    assert span.status.status_code is StatusCode.ERROR
    assert any(event.name == "exception" for event in span.events)


def test_disabled_facade_is_a_safe_noop() -> None:
    """Ensure init_tracing is a no-op when disabled and calls stay valid.

    With telemetry off no provider is installed, so the facade uses the API's
    no-op tracer: span() and record_exception() must not raise.
    """
    telemetry.init_tracing(None, SimpleNamespace(otel_enabled=False))
    with telemetry.span("noop", key="value"):
        telemetry.record_exception(RuntimeError("ignored"))
