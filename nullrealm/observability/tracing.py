"""OpenTelemetry tracing initialization for Null Realm."""

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def init_tracing():
    """Initialize OpenTelemetry tracing to Jaeger + Langfuse."""
    # OTLP to Jaeger
    jaeger_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    resource = Resource.create({"service.name": "null-realm"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=jaeger_endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)

    # OpenLLMetry for automatic LLM instrumentation
    # Uses existing TracerProvider (OTLP to Jaeger) — no Traceloop cloud API key needed
    try:
        from traceloop.sdk import Traceloop

        Traceloop.init(
            app_name="null-realm",
            disable_batch=False,
            exporter=OTLPSpanExporter(endpoint=jaeger_endpoint, insecure=True),
        )
    except Exception as e:
        print(f"Warning: OpenLLMetry init failed: {e}")

    # Langfuse callback (configured via env vars LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST)
