"""Contract tests for the existing endpoints (api-contract-spec sections 1-3, backend-spec section 4)."""
from __future__ import annotations

from conftest import INCIDENT


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert set(body) >= {"ok", "adapter", "clients", "db", "tracing"}


def test_create_returns_201_with_empty_log(client):
    r = client.post("/api/v1/incidents", json=INCIDENT)
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == "INC-101"
    assert body["log"] == [] and body["resolved"] is False and body["ticket"] is None
    assert client.get("/api/v1/incidents").json()[0]["id"] == "INC-101"


def test_duplicate_id_returns_409(client):
    assert client.post("/api/v1/incidents", json=INCIDENT).status_code == 201
    r = client.post("/api/v1/incidents", json=INCIDENT)
    assert r.status_code == 409


def test_log_appends_attributed_line_and_404_for_unknown(client):
    client.post("/api/v1/incidents", json=INCIDENT)
    r = client.post("/api/v1/incidents/INC-101/log", json={"text": "operator approved runbook rb-crac"})
    assert r.status_code == 200
    assert r.json()["log"] == ["operator approved runbook rb-crac (by dev-operator)"]
    assert client.post("/api/v1/incidents/INC-999/log", json={"text": "x"}).status_code == 404


def test_resolve_is_final(client):
    client.post("/api/v1/incidents", json=INCIDENT)
    r = client.post("/api/v1/incidents/INC-101/resolve")
    assert r.status_code == 200 and r.json()["resolved"] is True
    assert client.post("/api/v1/incidents/INC-101/resolve").status_code == 409
    assert client.post("/api/v1/incidents/INC-999/resolve").status_code == 404


def test_401_without_bearer_when_oidc(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "oidc")
    r = client.post("/api/v1/incidents", json=INCIDENT)
    assert r.status_code == 401 and r.json()["detail"] == "missing bearer token"
    assert client.get("/api/v1/incidents").status_code == 401
    r = client.post("/api/v1/incidents", json=INCIDENT, headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401 and r.json()["detail"].startswith("invalid token")


def test_dev_mode_needs_no_token(client):
    assert client.get("/api/v1/incidents").status_code == 200


def test_incident_enums_422(client):
    """backend-spec §4: kind/sev/runbook outside the catalogue → 422."""
    body = {"id": "INC-900", "kind": "other", "key": "B-02", "sev": "warn", "title": "t",
            "summary": "s", "rca": "r", "conf": 0.5, "runbook": "rb-airflow", "opened": "2026-10-17T00:00:00Z"}
    assert client.post("/api/v1/incidents", json=body).status_code == 422


def test_legacy_alias_still_answers(client):
    """Q1: /api/incidents is a deprecated alias until 2026-11-30."""
    body = {"id": "INC-901", "kind": "cpu", "key": "B-04", "sev": "warn", "title": "t",
            "summary": "s", "rca": "r", "conf": 0.5, "runbook": "rb-cpu", "opened": "2026-10-17T00:00:00Z"}
    assert client.post("/api/incidents", json=body).status_code == 201
