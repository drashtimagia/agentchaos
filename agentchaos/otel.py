"""OpenTelemetry export for AgentChaos traces.

Converts JSONL trace records into OTLP spans so runs appear in any
OpenTelemetry-compatible backend (Jaeger, Tempo, Honeycomb, etc.).

Install via the ``otel`` extra (``pip install 'agentchaos[otel]'``).

Usage
-----
    from agentchaos.otel import export_trace
    export_trace("results/my-run.jsonl")

Or from the CLI:
    agentchaos export-otel results/my-run.jsonl

Each run maps to one root span; each tool call and fault maps to a child span.
Span attributes follow the OpenTelemetry semantic conventions where applicable.
"""

from __future__ import annotations

from pathlib import Path

_OTEL_IMPORT_ERROR = (
    "Install the extra: pip install 'agentchaos[otel]'\n"
    "Required packages: opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc"
)


def export_trace(path: Path, *, endpoint: str = "http://localhost:4317") -> int:
    """Export all runs in ``path`` as OTLP spans.

    Returns the number of runs exported.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as e:
        raise RuntimeError(_OTEL_IMPORT_ERROR) from e

    from agentchaos.core.models import FaultRecord, OutcomeRecord, RunStart, ToolCallRecord
    from agentchaos.core.recorder import read_trace

    resource = Resource(attributes={"service.name": "agentchaos"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    tracer = trace.get_tracer("agentchaos", tracer_provider=provider)

    runs: dict[str, dict] = {}  # run_id -> {start, calls, faults, outcome}
    for record in read_trace(path):
        rid = record.run_id
        if rid not in runs:
            runs[rid] = {"start": None, "calls": [], "faults": [], "outcome": None}
        if isinstance(record, RunStart):
            runs[rid]["start"] = record
        elif isinstance(record, ToolCallRecord):
            runs[rid]["calls"].append(record)
        elif isinstance(record, FaultRecord):
            runs[rid]["faults"].append(record)
        elif isinstance(record, OutcomeRecord):
            runs[rid]["outcome"] = record

    for rid, data in runs.items():
        start = data["start"]
        outcome = data["outcome"]
        if start is None:
            continue

        with tracer.start_as_current_span(
            f"agentchaos.run:{start.scenario}",
            attributes={
                "agentchaos.run_id": rid,
                "agentchaos.scenario": start.scenario,
                "agentchaos.fault_class": start.fault_class,
                "agentchaos.agent": start.agent,
                "agentchaos.seed": start.seed,
            },
        ) as root:
            if outcome:
                root.set_attribute("agentchaos.task_success", outcome.task_success)
                root.set_attribute(
                    "agentchaos.safety_violations",
                    ",".join(outcome.safety_violations),
                )
                root.set_attribute("agentchaos.wall_time_s", outcome.wall_time_s)
                root.set_attribute("agentchaos.cost_usd", outcome.usage.cost_usd)

            faults_by_call: dict[int, list] = {}
            for f in data["faults"]:
                faults_by_call.setdefault(f.call_index, []).append(f)

            for call in data["calls"]:
                with tracer.start_as_current_span(
                    f"tool:{call.tool}",
                    attributes={
                        "agentchaos.tool": call.tool,
                        "agentchaos.call_index": call.index,
                        "agentchaos.ok": call.ok,
                    },
                ) as span:
                    for fault in faults_by_call.get(call.index, []):
                        span.add_event(
                            "fault_injected",
                            attributes={
                                "fault": fault.fault,
                                "rule": fault.rule,
                                "detail": str(fault.detail),
                            },
                        )

    provider.force_flush()
    provider.shutdown()
    return len(runs)
