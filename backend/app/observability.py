"""Per-stage timing, Prometheus metrics and OpenTelemetry spans.

Tracing is off unless OTEL_EXPORTER_OTLP_ENDPOINT is set; the spans are then no-ops from the OTel API.
Span attributes carry ids and sizes only, never question or chunk text (privacy rule in CLAUDE.md).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from prometheus_client import Counter, Gauge, Histogram

from app.config import Settings

tracer = trace.get_tracer("citesure")

STAGE_LATENCY = Histogram(
    "citesure_stage_latency_seconds",
    "Latency of each RAG pipeline stage",
    ["stage"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16),
)
ASK_TOTAL = Counter("citesure_ask_total", "Questions answered, by outcome", ["status"])
CLAIMS_DRAFTED = Counter("citesure_claims_drafted_total", "Claims the model drafted")
CLAIMS_DROPPED = Counter("citesure_claims_dropped_total", "Drafted claims removed by verification")
ASK_COST = Counter("citesure_ask_cost_usd_total", "Estimated LLM spend in USD")
INGEST_DOCS = Counter("citesure_ingest_documents_total", "Documents processed by the worker", ["status"])
QUEUE_DEPTH = Gauge("citesure_job_queue_depth", "Queued plus running background jobs")
HTTP_REQUESTS = Counter("citesure_http_requests_total", "HTTP requests", ["method", "status"])


class StageTimer:
    """Collects milliseconds per stage for one request and feeds metrics and spans."""

    def __init__(self) -> None:
        self.ms: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        with tracer.start_as_current_span(f"citesure.{name}"):
            try:
                yield
            finally:
                elapsed = time.perf_counter() - start
                self.ms[name] = self.ms.get(name, 0.0) + elapsed * 1000
                STAGE_LATENCY.labels(stage=name).observe(elapsed)


def setup_tracing(settings: Settings, service_name: str = "citesure-api") -> None:
    if not settings.otel_exporter_otlp_endpoint:
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name, "deployment.environment": settings.env})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"))
    )
    trace.set_tracer_provider(provider)
