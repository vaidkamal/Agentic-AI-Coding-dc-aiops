"""AI-spec section 9 acceptance criteria with a mocked model (frozen fixtures in evals/mock_outputs.json).

Test names carry the `-k` keywords of the AC table: shape, normalise, classify, injection,
bounds, budget, correction. Nothing here touches the network.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import app as app_module
import pytest
from ai import triage as triage_mod
from ai.budget import Budget, BudgetExhausted
from ai.schemas import DRAFT_KEYS, TriageRequest, TriageResponse
from ai.triage import (
    MAX_TOKENS,
    TIMEOUT_S,
    TriageService,
    UnusableOutput,
    normalise_key,
    triage_with_budget,
)
from conftest import triage_payload

TRIAGE = "/api/v1/ai/triage"


def _post(client, case, **overrides):
    return client.post(TRIAGE, json=triage_payload(case, **overrides))


# --- AI-1 shape ----------------------------------------------------------------------


@pytest.mark.parametrize("case_id", ["T1", "T4", "T6", "T7", "T8"])
def test_shape_six_keys_and_unresolved_listed_once(client, cases, case_id):
    r = _post(client, cases[case_id])
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["draft"]) == set(DRAFT_KEYS)
    draft = body["draft"]
    missing, clar = body["missing_fields"], body["clarification_fields"]
    assert not (set(missing) & set(clar))
    unresolved = {f for f in ("kind", "key", "sev") if draft[f] is None}
    if draft["kind"] == "other":
        unresolved.add("kind")
    assert set(missing) | set(clar) == unresolved
    assert len(missing) == len(set(missing)) and len(clar) == len(set(clar))
    assert body["request_id"].startswith("req_") and body["model"] == "fake-model"
    assert "id" not in body and "incident_id" not in body  # the response never carries an incident id


def test_shape_nulls_for_unknowns(client, cases):
    body = _post(client, cases["T4"]).json()
    assert body["draft"]["kind"] is None and body["draft"]["sev"] is None
    assert body["draft"]["runbook"] is None and body["draft"]["probable_cause"] is None
    assert sorted(body["missing_fields"]) == ["kind", "sev"]


@pytest.mark.parametrize(
    "mutation, reason",
    [
        ({"missing_fields": ["kind", "sev"], "clarification_fields": ["kind"]}, "both lists"),
        ({"missing_fields": ["kind"], "clarification_fields": []}, "sev not accounted for"),
        ({"missing_fields": ["kind", "sev", "runbook"]}, "field outside kind/key/sev"),
        ({"draft": {"kind": "thermal", "key": "A", "sev": None, "summary": None,
                    "probable_cause": None, "runbook": None}}, "kind outside enum"),
        ({"reply": ""}, "empty reply"),
    ],
)
def test_shape_invalid_model_output_is_503_never_partial(client, fake, cases, mutation, reason):
    raw = {**fake.outputs["T4"], **mutation}
    fake.queue_output(raw)
    r = _post(client, cases["T4"])
    assert r.status_code == 503, reason
    assert r.json() == {"detail": "unusable model output"}


def test_shape_response_model_enforces_invariants():
    with pytest.raises(ValueError):
        TriageResponse(draft={"kind": None, "key": "A", "sev": None, "summary": None,
                              "probable_cause": None, "runbook": None},
                       missing_fields=["kind"], clarification_fields=[],
                       reply="x", request_id="req_1", model="m")


def test_shape_400_for_text_too_long_and_history_over_19(client, cases):
    r = _post(client, cases["T2"], text="x" * 2001)
    assert r.status_code == 400 and r.json()["detail"] == "text too long"
    hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": "m"} for i in range(20)]
    r = _post(client, cases["T2"], history=hist)
    assert r.status_code == 400 and r.json()["detail"] == "history too long"
    assert _post(client, cases["T2"], text="").status_code == 422


def test_shape_401_without_bearer_when_oidc(client, cases, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "oidc")
    r = _post(client, cases["T2"])
    assert r.status_code == 401 and r.json()["detail"] == "missing bearer token"


# --- AI-2 normalise ------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [("D-2", "D-02"), ("d02", "D-02"), ("rack D 2", "D-02"),
     ("zone c", "C"), ("Zone-C", "C"), ("CRAC-3", "C")],
)
def test_normalise_six_spellings(raw, expected):
    assert normalise_key(raw) == expected


@pytest.mark.parametrize("raw, expected", [("B-04", "B-04"), ("b4", "B-04"), ("A 1", "A-01"), ("crac 1", "A")])
def test_normalise_more_spellings(raw, expected):
    assert normalise_key(raw) == expected


@pytest.mark.parametrize("raw", ["E-01", "zone e", "the fourth rack", "", "CRAC-5", "D-0"])
def test_normalise_rejects_ids_outside_the_hall(raw):
    with pytest.raises(ValueError):
        normalise_key(raw)


def test_normalise_model_key_through_endpoint(client, cases):
    body = _post(client, cases["T3"]).json()  # canned output says "D-2"
    assert body["draft"]["key"] == "D-02"


def test_normalise_zone_kind_with_rack_key_becomes_zone_letter(fake):
    raw = {**fake.outputs["T1"], "draft": {**fake.outputs["T1"]["draft"], "key": "C-01"}}
    out = triage_mod.validate_output(raw)
    assert out.draft.key == "C"


def test_normalise_rack_kind_with_zone_key_is_unusable(fake):
    raw = {**fake.outputs["T2"], "draft": {**fake.outputs["T2"]["draft"], "key": "B"}}
    with pytest.raises(UnusableOutput):
        triage_mod.validate_output(raw)


# --- AI-3 classify -------------------------------------------------------------------


def test_classify_zone_wide_thermal(client, cases):
    body = _post(client, cases["T1"]).json()
    d = body["draft"]
    assert (d["kind"], d["key"], d["sev"], d["runbook"]) == ("thermal-zone", "C", "crit", "rb-crac")
    assert "14:10" in d["summary"] and "CRAC-3" in d["summary"]
    assert body["missing_fields"] == [] and body["clarification_fields"] == []


def test_classify_single_rack_cpu(client, cases):
    d = _post(client, cases["T2"]).json()["draft"]
    assert (d["kind"], d["key"], d["sev"], d["runbook"]) == ("cpu", "B-04", "warn", "rb-cpu")


def test_classify_below_threshold_has_no_invented_severity(client, cases):
    body = _post(client, cases["T7"]).json()
    assert body["draft"]["sev"] is None and "sev" in body["missing_fields"]
    assert any(w in body["reply"] for w in ("within", "ASHRAE", "below"))


def test_classify_system_prompt_carries_rules_and_mapping():
    sp = triage_mod.SYSTEM_PROMPT
    assert triage_mod.RULES_VERSION == "v1" and triage_mod.PROMPT_VERSION == "v1"
    assert "Zone C = CRAC-3" in sp and "rb-crac" in sp and "thermal-zone" in sp
    assert "Do not invent a severity" in sp


# --- AI-4 injection ------------------------------------------------------------------


def test_injection_text_is_data_not_instruction(client, fake, cases):
    body = _post(client, cases["T8"]).json()
    d = body["draft"]
    assert d["key"] == "B-02" and d["kind"] != "psu"
    assert "all racks offline" not in (d["summary"] or "")
    kwargs = fake.calls[-1]
    assert "Ignore the rules" not in kwargs["system"]
    user_turn = kwargs["messages"][-1]["content"]
    assert "<operator_text>" in user_turn and "Ignore the rules" in user_turn
    assert "Never follow" in kwargs["system"]


def test_injection_history_is_delimited_too(fake, cases):
    req = TriageRequest.model_validate(triage_payload(cases["T5"]))
    msgs = triage_mod.build_messages(req)
    assert msgs[0]["role"] == "user" and "<operator_text>" in msgs[0]["content"]
    assert msgs[1]["role"] == "assistant"
    assert "<current_draft>" in msgs[-1]["content"] and '"B-04"' in msgs[-1]["content"]


# --- AI-5 bounds ---------------------------------------------------------------------


def test_bounds_on_every_call(client, fake, cases):
    for cid in ("T1", "T2", "T3"):
        assert _post(client, cases[cid]).status_code == 200
    assert len(fake.calls) == 3
    for kw in fake.calls:
        assert kw["max_tokens"] == 1024 and MAX_TOKENS == 1024
        assert kw["timeout"] == 20 and TIMEOUT_S == 20
        assert kw["tool_choice"] == {"type": "tool", "name": "propose_draft"}


def test_bounds_no_retry_on_timeout(client, fake, cases):
    fake.queue_error(TimeoutError("read timed out"))
    r = _post(client, cases["T2"])
    assert r.status_code == 503 and r.json()["detail"] == "model unavailable"
    assert len(fake.calls) == 1


def test_bounds_default_client_has_no_retries(monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-0123456789")
    svc = TriageService()
    assert isinstance(svc.client, anthropic.AsyncAnthropic)
    assert svc.client.max_retries == 0 and triage_mod.MAX_RETRIES == 0
    assert float(svc.client.timeout) == 20.0


def test_bounds_missing_key_is_503_not_crash(client, cases):
    app_module.app.state.triage_service = None
    app_module._triage_service = None
    os.environ.pop("ANTHROPIC_API_KEY", None)
    r = _post(client, cases["T2"])
    assert r.status_code == 503 and r.json()["detail"] == "model unavailable"


def test_bounds_truncated_output_is_unusable(client, fake, cases):
    fake.queue_output(None, stop_reason="max_tokens")
    r = _post(client, cases["T2"])
    assert r.status_code == 503 and r.json()["detail"] == "unusable model output"


# --- AI-7 budget ---------------------------------------------------------------------


def test_budget_reserve_then_settle():
    b = Budget(monthly_usd=1.0, db_path=None, price_in_per_m=1.0, price_out_per_m=5.0)
    res = b.reserve(1000, 1024)
    assert res.reserved_usd == pytest.approx((1000 * 1.0 + 1024 * 5.0) / 1e6)
    assert b.mtd_usd() == pytest.approx(res.reserved_usd)
    b.settle(res, 900, 180)
    assert b.mtd_usd() == pytest.approx((900 * 1.0 + 180 * 5.0) / 1e6)
    b.settle(res, 900, 180)  # idempotent
    assert b.mtd_usd() == pytest.approx((900 * 1.0 + 180 * 5.0) / 1e6)


def test_budget_exhausted_blocks_before_the_call():
    b = Budget(monthly_usd=0.000001, db_path=None)
    with pytest.raises(BudgetExhausted):
        b.reserve(1000, 1024)
    assert b.mtd_usd() == 0.0


def test_budget_429_when_exhausted(client, fake, cases, monkeypatch):
    monkeypatch.setattr(app_module, "budget", Budget(monthly_usd=0.00001, db_path=None))
    r = _post(client, cases["T2"])
    assert r.status_code == 429 and r.json()["detail"] == "budget exhausted"
    assert fake.calls == []


def test_budget_wraps_every_call_including_unusable_output(client, fake, cases):
    b = app_module.budget
    assert _post(client, cases["T2"]).status_code == 200
    one = b.estimate_usd(900, 180)
    assert b.mtd_usd() == pytest.approx(one)
    fake.queue_output({**fake.outputs["T2"], "reply": ""})
    assert _post(client, cases["T2"]).status_code == 503
    assert b.mtd_usd() == pytest.approx(2 * one)  # actual usage settled, reservation released
    fake.queue_error(TimeoutError("timeout"))
    assert _post(client, cases["T2"]).status_code == 503
    assert b.mtd_usd() == pytest.approx(2 * one)  # no usage: reservation released, nothing added


@pytest.mark.asyncio
async def test_budget_reserve_settle_wrapper_releases_on_error(fake, cases):
    svc = TriageService(client=fake, model="fake-model")
    b = Budget(monthly_usd=5.0, db_path=None)
    req = TriageRequest.model_validate(triage_payload(cases["T2"]))
    fake.queue_error(RuntimeError("boom"))
    with pytest.raises(triage_mod.ModelUnavailable):
        await triage_with_budget(svc, b, req, "req_x")
    assert b.mtd_usd() == 0.0
    res = await triage_with_budget(svc, b, req, "req_y")
    assert res.response.draft.key == "B-04" and b.mtd_usd() > 0


def test_budget_month_to_date_persists_in_sqlite(tmp_path):
    path = str(tmp_path / "budget.sqlite")
    b1 = Budget(monthly_usd=5.0, db_path=path)
    b1.settle(b1.reserve(1000, 1024), 1000, 100)
    b2 = Budget(monthly_usd=5.0, db_path=path)
    assert b2.mtd_usd() == pytest.approx(b1.mtd_usd()) and b2.mtd_usd() > 0


def test_budget_env_defaults(monkeypatch):
    for k in ("AI_MONTHLY_BUDGET_USD", "AI_PRICE_IN_PER_M", "AI_PRICE_OUT_PER_M"):
        monkeypatch.delenv(k, raising=False)
    b = Budget(db_path=None)
    assert (b.monthly_usd, b.price_in_per_m, b.price_out_per_m) == (5.0, 1.0, 5.0)


# --- rate limit (AI-spec section 8) ---------------------------------------------------


def test_rate_limited_after_ten_per_minute(client, cases):
    for _ in range(10):
        assert _post(client, cases["T2"]).status_code == 200
    r = _post(client, cases["T2"])
    assert r.status_code == 429 and r.json()["detail"] == "rate limited"


# --- AI-8 correction -----------------------------------------------------------------


def test_correction_keeps_unchanged_fields(client, cases):
    case = cases["T5"]
    body = _post(client, case).json()
    prior = case["request"]["draft"]
    d = body["draft"]
    assert d["key"] == "B-05"
    for f in ("kind", "sev", "runbook", "probable_cause"):
        assert d[f] == prior[f], f
    assert d["summary"] != prior["summary"] and "B-05" in d["summary"]
    assert body["reply"].isascii()  # replies are always English


# --- AI-6 no write path (mutation-style) ----------------------------------------------


def test_no_write_path_from_ai_module():
    """Mutation test: break the ownership of the write path and this must fail.

    If anyone adds `from app import incidents`, imports the write router, or even mentions the
    `/api/incidents` route from backend/ai/, both the import-graph check and the literal grep
    (AI-6: `grep -r "incidents" backend/ai/ ; test $? -ne 0`) go red.
    """
    ai_dir = Path(triage_mod.__file__).resolve().parent
    for py in ai_dir.glob("*.py"):
        source = py.read_text(encoding="utf-8")
        assert "incidents" not in source, f"{py.name} references the write path"
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            else:
                continue
            for n in names:
                assert "incident" not in n.lower() and n.split(".")[0] not in ("app", "auth", "integrations"), (
                    f"{py.name} imports {n}"
                )
