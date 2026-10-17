"""OpenTelemetry tracing for AI triage (observability-spec.md).

- Exports OTLP/HTTP to PHOENIX_COLLECTOR_ENDPOINT when set; otherwise every span is a
  no-op and tracing_status() reports "off" so the capture gap is visible on /healthz.
- Every attribute value passes through redact(): the provider API key, bearer tokens
  and JWT-shaped strings never reach a span (section 3).
- Versions (app.version, prompt_version, rules_version, model, grader.version) are
  stamped on every span by a span processor (section 4).
- Tests install an in-memory exporter through setup_tracing(exporter=...).
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter

SERVICE_NAME = "dc-aiops"
PROJECT_NAME = "dc-aiops-local"
TRACER_NAME = "dc-aiops.ai"

SPAN_HTTP_TRIAGE = "http POST /api/v1/ai/triage"
SPAN_BUDGET_RESERVE = "budget.reserve"
SPAN_ANTHROPIC_TRIAGE = "anthropic.triage"
SPAN_TRIAGE_VALIDATE = "triage.validate"
SPAN_BUDGET_SETTLE = "budget.settle"
SPAN_INCIDENT_SAVE = "incident.save"

_provider: TracerProvider | None = None
_status = "off"
_common_attrs: dict[str, Any] = {}
_global_provider_set = False

# ---- redaction ------------------------------------------------------------------

_KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<![\w:\-])\+?\d[\d\s().\-]{7,}\d(?![\w:])")

REDACTED = "[redacted]"


def redact(value: str) -> str:
    """Mask the provider key, bearer tokens and JWTs wherever they appear in a string."""
    out = _KEY_RE.sub(REDACTED, value)
    out = _BEARER_RE.sub("Bearer " + REDACTED, out)
    out = _JWT_RE.sub(REDACTED, out)
    secret = os.environ.get("ANTHROPIC_API_KEY", "")
    if len(secret) >= 8 and secret in out:
        out = out.replace(secret, REDACTED)
    return out


def sanitise_text(value: str) -> str:
    """Operator text as stored on a span: secrets redacted, emails and phone numbers masked."""
    out = redact(value)
    out = _EMAIL_RE.sub("[email]", out)
    out = _PHONE_RE.sub("[phone]", out)
    return out


def _coerce(value: Any) -> Any:
    if value is None:
        return "null"
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list | tuple) and all(isinstance(v, str) for v in value):
        return [redact(v) for v in value]
    return redact(json.dumps(value, ensure_ascii=False, default=str))


def set_attributes(span: trace.Span, attrs: dict[str, Any]) -> None:
    for k, v in attrs.items():
        span.set_attribute(k, _coerce(v))


# ---- setup ----------------------------------------------------------------------


class _CommonAttributes(SpanProcessor):
    def on_start(self, span, parent_context=None) -> None:  # type: ignore[override]
        if _common_attrs:
            set_attributes(span, _common_attrs)


def set_common_attributes(**attrs: Any) -> None:
    """Attributes stamped on every span (prompt_version, rules_version, model, grader.version)."""
    for k, v in attrs.items():
        if v is None:
            _common_attrs.pop(k, None)
        else:
            _common_attrs[k] = v


def setup_tracing(endpoint: str | None = None, exporter: SpanExporter | None = None) -> str:
    """Configure tracing. Returns the resulting status ("on" / "off").

    endpoint: OTLP/HTTP collector (defaults to PHOENIX_COLLECTOR_ENDPOINT).
    exporter: an explicit SpanExporter (tests pass InMemorySpanExporter); wins over endpoint.
    """
    global _provider, _status, _global_provider_set
    if _provider is not None:
        _provider.shutdown()
        _provider = None
    if endpoint is None:
        endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT") or None
    processor: SpanProcessor | None = None
    if exporter is not None:
        processor = SimpleSpanProcessor(exporter)
    elif endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    if processor is None:
        _status = "off"
        return _status
    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            "openinference.project.name": PROJECT_NAME,
            "app.version": os.environ.get("APP_VERSION", os.environ.get("GIT_SHA", "dev")),
        }
    )
    set_common_attributes(app_version=resource.attributes["app.version"])
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(_CommonAttributes())
    provider.add_span_processor(processor)
    _provider = provider
    if not _global_provider_set:
        trace.set_tracer_provider(provider)
        _global_provider_set = True
    _status = "on"
    return _status


def reset_tracing() -> None:
    """Drop the active provider; tracing becomes a no-op again (used by tests)."""
    global _provider, _status
    if _provider is not None:
        _provider.shutdown()
    _provider = None
    _status = "off"


def tracing_status() -> str:
    return _status


def tracer() -> trace.Tracer:
    if _provider is None:
        return trace.NoOpTracer()
    return _provider.get_tracer(TRACER_NAME)


# ---- span helpers (names from observability-spec section 1) ------------------------


@contextmanager
def span(name: str, attrs: dict[str, Any] | None = None) -> Iterator[trace.Span]:
    with tracer().start_as_current_span(name) as s:
        if attrs:
            set_attributes(s, attrs)
        yield s


@contextmanager
def http_triage_span(
    *, request_id: str, sub_hash: str, hall: str, history_len: int, input_chars: int
) -> Iterator[trace.Span]:
    with span(
        SPAN_HTTP_TRIAGE,
        {
            "request_id": request_id,
            "user.sub_hash": sub_hash,
            "hall": hall,
            "history_len": history_len,
            "input.chars": input_chars,
        },
    ) as s:
        yield s


@contextmanager
def budget_reserve_span() -> Iterator[trace.Span]:
    with span(SPAN_BUDGET_RESERVE) as s:
        yield s


@contextmanager
def anthropic_triage_span(*, model: str, max_tokens: int, timeout_s: float) -> Iterator[trace.Span]:
    with span(
        SPAN_ANTHROPIC_TRIAGE, {"model": model, "max_tokens": max_tokens, "timeout_s": timeout_s}
    ) as s:
        yield s


@contextmanager
def triage_validate_span() -> Iterator[trace.Span]:
    with span(SPAN_TRIAGE_VALIDATE) as s:
        yield s


@contextmanager
def budget_settle_span() -> Iterator[trace.Span]:
    with span(SPAN_BUDGET_SETTLE) as s:
        yield s


@contextmanager
def incident_save_span(
    *, incident_id: str, draft_request_id: str | None, fields_changed_by_operator: list[str]
) -> Iterator[trace.Span]:
    """Separate trace emitted by the write path when the operator confirms (linked by request_id)."""
    with span(
        SPAN_INCIDENT_SAVE,
        {
            "incident_id": incident_id,
            "draft_request_id": draft_request_id,
            "fields_changed_by_operator": list(fields_changed_by_operator),
        },
    ) as s:
        yield s
