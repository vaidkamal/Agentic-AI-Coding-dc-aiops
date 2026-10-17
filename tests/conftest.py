"""Shared fixtures. Run with `cd backend && pytest -q` (also works from the repo root via the
`tests` symlink). No network: the model is a fake client fed with frozen canned outputs."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
for p in (str(BACKEND_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Environment must be settled before `app` is imported (it reads env at import time).
os.environ.setdefault("AUTH_MODE", "dev")
os.environ.setdefault("TICKETING", "none")
os.environ.setdefault("TELEMETRY_ADAPTER", "simulator")
os.environ.pop("PHOENIX_COLLECTOR_ENDPOINT", None)
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("AI_BUDGET_DB", None)

import app as app_module  # noqa: E402
from ai import tracing  # noqa: E402
from ai.budget import Budget  # noqa: E402
from ai.triage import TriageService  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from evals.mock_client import FakeAnthropic, load_cases  # noqa: E402

GOLDEN = REPO_ROOT / "evals" / "golden" / "cases.json"


@pytest.fixture(scope="session")
def cases() -> dict[str, dict]:
    return {c["id"]: c for c in load_cases(GOLDEN)}


@pytest.fixture
def fake() -> FakeAnthropic:
    return FakeAnthropic()


@pytest.fixture
def service(fake: FakeAnthropic) -> TriageService:
    return TriageService(client=fake, model="fake-model")


@pytest.fixture(autouse=True)
def _fresh_app_state(fake: FakeAnthropic, monkeypatch: pytest.MonkeyPatch):
    """Every test starts with no saved records, a full rate bucket, an empty budget and the fake model."""
    app_module.incidents.clear()
    app_module.limiter.reset()
    monkeypatch.setattr(app_module, "budget", Budget(monthly_usd=5.0, db_path=None))
    app_module.app.state.triage_service = TriageService(client=fake, model="fake-model")
    yield
    app_module.app.state.triage_service = None
    app_module.incidents.clear()
    app_module.limiter.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app_module.app)


@pytest.fixture
def exporter():
    """In-memory span exporter installed for the test, tracing reset afterwards."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exp = InMemorySpanExporter()
    tracing.setup_tracing(exporter=exp)
    yield exp
    tracing.reset_tracing()


def triage_payload(case: dict, **overrides) -> dict:
    body = {
        "text": case["request"]["text"],
        "draft": case["request"].get("draft"),
        "history": case["request"].get("history", []),
        "context": {"hall": "H2", "now": "2026-10-17T15:40:00Z"},
    }
    body.update(overrides)
    return json.loads(json.dumps(body))


INCIDENT = {
    "id": "INC-101", "kind": "thermal-zone", "key": "C", "sev": "crit",
    "title": "Zone C thermal excursion",
    "summary": "3 racks in Zone C rose above baseline together (C-01, C-03, C-05).",
    "rca": "CRAC-3 is the only shared cooling dependency for these racks.",
    "conf": 0.91, "runbook": "rb-crac", "opened": "2026-10-17T15:42:10Z",
}
