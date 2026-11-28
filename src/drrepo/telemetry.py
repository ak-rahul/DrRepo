"""Optional OpenTelemetry traces: one trace per analysis, a span per collector and category.

Install the extra (`uv sync --extra otel`) and set `OTEL_EXPORTER_OTLP_ENDPOINT`
(for example `http://localhost:4318`); `configure_tracing` then exports spans
over OTLP/HTTP. Without the extra, or without an endpoint, every `span()` is a
no-op and costs nothing.

LangGraph runs nodes on worker threads, where OpenTelemetry's current-span
context doesn't follow. So the analysis span's context is kept on the run
(`RunContext.trace_parent`) and passed explicitly as each node span's parent.

    drrepo.analysis     repo, ref, commit, overall_score
      drrepo.collector  collector, status
      drrepo.category   category, depth, score, issues, tokens
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from typing import Any

from drrepo import __version__
from drrepo.config import Config
from drrepo.log import logger

# Process-wide, like OpenTelemetry's own tracer provider: set at most once.
_setup = {"done": False}
_setup_lock = threading.Lock()


def configure_tracing(config: Config) -> bool:
    """Export spans over OTLP/HTTP when an endpoint is set and the extra is installed."""
    if not config.otel_endpoint:
        return False
    with _setup_lock:
        if _setup["done"]:
            return True
        return _install(config.otel_endpoint)


def _install(endpoint_base: str) -> bool:
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OTEL_EXPORTER_OTLP_ENDPOINT is set, but the otel extra isn't installed")
        return False
    provider = TracerProvider(
        resource=Resource.create({"service.name": "drrepo", "service.version": __version__})
    )
    endpoint = endpoint_base.rstrip("/") + "/v1/traces"
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    _setup["done"] = True
    logger.info(f"Exporting traces to {endpoint}")
    return True


def _tracer() -> Any:
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    return trace.get_tracer("drrepo", __version__)


@contextlib.contextmanager
def span(name: str, parent: Any = None, **attributes: Any) -> Iterator[Any]:
    """A span (or None without OpenTelemetry). `parent` is a context from `current_context()`."""
    tracer = _tracer()
    if tracer is None:
        yield None
        return
    clean = {k: v for k, v in attributes.items() if isinstance(v, (str, bool, int, float))}
    with tracer.start_as_current_span(name, context=parent, attributes=clean) as current:
        yield current


def current_context() -> Any:
    """The active OpenTelemetry context, to parent spans started on other threads."""
    try:
        from opentelemetry import context
    except ImportError:
        return None
    return context.get_current()


def set_attributes(current: Any, **attributes: Any) -> None:
    if current is None:
        return
    for key, value in attributes.items():
        if isinstance(value, (str, bool, int, float)):
            current.set_attribute(key, value)
