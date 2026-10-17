"""Ticketing integration (ServiceNow / Jira) through the incident lifecycle.

backend-spec §4: "Ticket sync must not block the operator" — a failure is logged as a timeline
event and the request still succeeds. api-contract §1: create opens a ticket, log adds a work
note / comment, resolve closes it. Integration modules are stubbed; no network.
"""
import app as appmod

INC = {"id": "INC-700", "kind": "thermal-zone", "key": "C", "sev": "crit", "title": "Zone C thermal excursion",
       "summary": "3 racks rose together", "rca": "CRAC-3", "conf": 0.91, "runbook": "rb-crac",
       "opened": "2026-10-17T15:42:10Z"}


class Stub:
    """Records calls; optionally fails on a given operation."""
    def __init__(self, ref="TKT-1", fail_on=None):
        self.ref, self.fail_on, self.calls = ref, fail_on, []

    async def create(self, rec):
        self.calls.append(("create", rec["id"]))
        if self.fail_on == "create":
            raise RuntimeError("ticketing down")
        return self.ref

    async def comment(self, ref, text):
        self.calls.append(("comment", ref, text))
        if self.fail_on == "comment":
            raise RuntimeError("ticketing down")

    async def resolve(self, ref):
        self.calls.append(("resolve", ref))
        if self.fail_on == "resolve":
            raise RuntimeError("ticketing down")


def _wire(monkeypatch, system, stub):
    monkeypatch.setattr(appmod, "TICKETING", system)
    monkeypatch.setattr(appmod, system, stub)   # app imports the module by name: servicenow / jira


def _lifecycle(client):
    r = client.post("/api/v1/incidents", json=INC)
    assert r.status_code == 201, r.text
    r2 = client.post("/api/v1/incidents/INC-700/log", json={"text": "operator approved runbook Cooling failover"})
    assert r2.status_code == 200
    r3 = client.post("/api/v1/incidents/INC-700/resolve")
    assert r3.status_code == 200
    return r.json(), r2.json(), r3.json()


def test_servicenow_create_note_close(client, monkeypatch):
    stub = Stub(ref="sys_abc")
    _wire(monkeypatch, "servicenow", stub)
    created, noted, resolved = _lifecycle(client)
    assert created["ticket"] == "sys_abc"
    assert [c[0] for c in stub.calls] == ["create", "comment", "resolve"]
    assert stub.calls[1][1] == "sys_abc" and "approved runbook" in stub.calls[1][2]
    assert "(by dev-operator)" in stub.calls[1][2]          # actor from the token
    assert resolved["resolved"] is True


def test_jira_create_comment_transition(client, monkeypatch):
    stub = Stub(ref="DCOPS-42")
    _wire(monkeypatch, "jira", stub)
    created, _, resolved = _lifecycle(client)
    assert created["ticket"] == "DCOPS-42"
    assert stub.calls[-1] == ("resolve", "DCOPS-42")


def test_ticketing_failure_never_blocks_the_operator(client, monkeypatch):
    stub = Stub(fail_on="create")
    _wire(monkeypatch, "servicenow", stub)
    r = client.post("/api/v1/incidents", json=INC)
    assert r.status_code == 201                              # incident still saved
    body = r.json()
    assert body["ticket"] is None
    assert any("ticket sync failed" in line for line in body["log"])   # visible in the timeline


def test_ticketing_failure_on_resolve_still_resolves(client, monkeypatch):
    stub = Stub(fail_on="resolve")
    _wire(monkeypatch, "servicenow", stub)
    client.post("/api/v1/incidents", json=INC)
    r = client.post("/api/v1/incidents/INC-700/resolve")
    assert r.status_code == 200 and r.json()["resolved"] is True
    assert any("ticket sync failed" in line for line in r.json()["log"])


def test_no_ticketing_means_no_calls(client, monkeypatch):
    stub = Stub()
    monkeypatch.setattr(appmod, "TICKETING", "none")
    monkeypatch.setattr(appmod, "servicenow", stub)
    created, _, _ = _lifecycle(client)
    assert created["ticket"] is None and stub.calls == []
