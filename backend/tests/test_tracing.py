"""observability-spec section 6: OBS-1 spans, OBS-2 redaction, OBS-3 healthz tracing flag."""
from __future__ import annotations

import pytest
from ai import tracing
from conftest import INCIDENT, triage_payload

TRIAGE = "/api/v1/ai/triage"
TRIAGE_SPANS = {
    tracing.SPAN_HTTP_TRIAGE,
    tracing.SPAN_BUDGET_RESERVE,
    tracing.SPAN_ANTHROPIC_TRIAGE,
    tracing.SPAN_TRIAGE_VALIDATE,
    tracing.SPAN_BUDGET_SETTLE,
}


def _by_name(exporter):
    return {s.name: s for s in exporter.get_finished_spans()}


def test_spans_one_trace_with_the_triage_spans(client, exporter, cases):
    r = client.post(TRIAGE, json=triage_payload(cases["T3"]))
    assert r.status_code == 200
    spans = _by_name(exporter)
    assert TRIAGE_SPANS <= set(spans), set(spans)
    trace_ids = {s.context.trace_id for n, s in spans.items() if n in TRIAGE_SPANS}
    assert len(trace_ids) == 1, "all five spans belong to one trace"

    http = spans[tracing.SPAN_HTTP_TRIAGE].attributes
    assert http["request_id"] == r.json()["request_id"]
    assert len(http["user.sub_hash"]) == 12 and http["hall"] == "H2"
    assert http["history_len"] == 0 and http["input.chars"] == len(cases["T3"]["request"]["text"])
    assert http["http.status_code"] == 200 and http["latency_ms"] >= 0

    reserve = spans[tracing.SPAN_BUDGET_RESERVE].attributes
    assert reserve["allowed"] is True and reserve["reserved_usd"] > 0 and reserve["mtd_usd_before"] == 0

    model = spans[tracing.SPAN_ANTHROPIC_TRIAGE].attributes
    assert model["model"] == "fake-model" and model["max_tokens"] == 1024 and model["timeout_s"] == 20
    assert model["prompt_version"] == "v1" and model["rules_version"] == "v1"
    assert model["usage.input_tokens"] == 900 and model["usage.output_tokens"] == 180
    assert model["stop_reason"] == "tool_use"
    assert "D-2" in model["input.text"] and '"key": "D-02"' in model["output.draft"]
    assert model["input.draft"] == "null"
    assert list(model["output.missing_fields"]) == []

    validate = spans[tracing.SPAN_TRIAGE_VALIDATE].attributes
    assert validate["valid"] is True
    assert validate["normalised_key_from"] == "D-2" and validate["normalised_key_to"] == "D-02"

    settle = spans[tracing.SPAN_BUDGET_SETTLE].attributes
    assert settle["actual_usd"] > 0 and settle["mtd_usd_after"] == pytest.approx(settle["actual_usd"])

    for s in spans.values():  # section 4: versions on every span
        assert s.attributes["prompt_version"] == "v1" and s.attributes["rules_version"] == "v1"
        assert s.attributes["model"] == "fake-model"
        assert s.resource.attributes["service.name"] == "dc-aiops"


def test_spans_rejection_reason_on_unusable_output(client, exporter, fake, cases):
    fake.queue_output({**fake.outputs["T2"], "missing_fields": ["kind"]})
    r = client.post(TRIAGE, json=triage_payload(cases["T2"]))
    assert r.status_code == 503
    spans = _by_name(exporter)
    v = spans[tracing.SPAN_TRIAGE_VALIDATE].attributes
    assert v["valid"] is False and "missing_fields" in v["rejection_reason"]
    assert spans[tracing.SPAN_HTTP_TRIAGE].attributes["http.status_code"] == 503
    assert tracing.SPAN_BUDGET_SETTLE in spans  # actual usage still settled


def test_spans_budget_blocked_is_visible(client, exporter, cases, monkeypatch):
    import app as app_module
    from ai.budget import Budget

    monkeypatch.setattr(app_module, "budget", Budget(monthly_usd=0.00001, db_path=None))
    assert client.post(TRIAGE, json=triage_payload(cases["T2"])).status_code == 429
    spans = _by_name(exporter)
    assert spans[tracing.SPAN_BUDGET_RESERVE].attributes["allowed"] is False
    assert tracing.SPAN_ANTHROPIC_TRIAGE not in spans


def test_spans_incident_save_is_a_separate_trace_linked_by_request_id(client, exporter):
    r = client.post("/api/incidents", json=INCIDENT,
                    headers={"X-Draft-Request-Id": "req_abc", "X-Draft-Fields-Changed": "sev, summary"})
    assert r.status_code == 201
    s = _by_name(exporter)[tracing.SPAN_INCIDENT_SAVE]
    assert s.attributes["incident_id"] == "INC-101"
    assert s.attributes["draft_request_id"] == "req_abc"
    assert list(s.attributes["fields_changed_by_operator"]) == ["sev", "summary"]
    assert s.parent is None


SECRET = "sk-ant-api03-SUPERSECRETVALUE1234567890"
JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJvcHMifQ.c2lnbmF0dXJl"


def _all_attribute_values(exporter):
    out = []
    for s in exporter.get_finished_spans():
        for v in s.attributes.values():
            out.extend(v if isinstance(v, tuple | list) else [v])
    return [str(v) for v in out]


def test_redaction_of_api_key_and_bearer_in_spans(client, exporter, fake, cases, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    text = f"B-04 pegged at 98% CPU. key={SECRET} Authorization: Bearer {JWT} mail ops@dc.example +44 20 7946 0958"
    fake.queue_output(fake.outputs["T2"])
    r = client.post(TRIAGE, json=triage_payload(cases["T2"], text=text),
                    headers={"Authorization": f"Bearer {JWT}"})
    assert r.status_code == 200
    values = _all_attribute_values(exporter)
    assert values, "spans were exported"
    for v in values:
        assert SECRET not in v and JWT not in v and "Bearer eyJ" not in v
        assert "ops@dc.example" not in v and "7946 0958" not in v
    model = _by_name(exporter)[tracing.SPAN_ANTHROPIC_TRIAGE].attributes
    assert "[redacted]" in model["input.text"] and "[email]" in model["input.text"]


def test_redaction_also_covers_provider_errors(client, exporter, fake, cases, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    fake.queue_error(RuntimeError(f"401 invalid x-api-key {SECRET}"))
    assert client.post(TRIAGE, json=triage_payload(cases["T2"])).status_code == 503
    for v in _all_attribute_values(exporter):
        assert SECRET not in v


def test_redaction_helpers():
    assert tracing.redact(f"token {SECRET}") == "token [redacted]"
    assert tracing.redact(f"Authorization: Bearer {JWT}") == "Authorization: Bearer [redacted]"
    assert tracing.sanitise_text("call +1 (415) 555-0100 or a.b@example.org") == "call [phone] or [email]"
    assert tracing.sanitise_text("C-01 at 29°C since 14:10") == "C-01 at 29°C since 14:10"


def test_healthz_tracing_off_when_collector_unset(client, monkeypatch):
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    tracing.reset_tracing()
    assert tracing.setup_tracing() == "off"
    assert client.get("/healthz").json()["tracing"] == "off"


def test_healthz_tracing_on_with_exporter(client, exporter):
    assert client.get("/healthz").json()["tracing"] == "on"


def test_healthz_tracing_on_with_collector_endpoint(client, monkeypatch):
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006/v1/traces")
    try:
        assert tracing.setup_tracing() == "on"
        assert client.get("/healthz").json()["tracing"] == "on"
    finally:
        tracing.reset_tracing()
