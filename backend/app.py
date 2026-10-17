"""DC-North AIOps backend.
FastAPI service that streams rack telemetry to the console over WebSocket,
persists incidents, and forwards them to ServiceNow / Jira.
Run: uvicorn app:app --host 0.0.0.0 --port 8080
"""
import asyncio, hashlib, json, os, secrets, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Literal
from adapters import prometheus, simulator
from integrations import servicenow, jira
from auth import current_user
from ai import tracing
from ai.budget import Budget, BudgetExhausted
from ai.ratelimit import TokenBucket
from ai.schemas import TriageRequest, TriageResponse
from ai.triage import ModelUnavailable, TriageService, UnusableOutput, triage_with_budget

POLL_SECONDS = float(os.getenv("POLL_SECONDS", "2"))
ADAPTER = os.getenv("TELEMETRY_ADAPTER", "simulator")   # simulator | prometheus
TICKETING = os.getenv("TICKETING", "none")               # none | servicenow | jira

clients: set[WebSocket] = set()
incidents: dict[str, dict] = {}
latest: dict = {}

# --- AI triage (AI-spec §8, backend-spec Rev 2 §10, observability-spec) ---
tracing.setup_tracing()                       # no-op unless PHOENIX_COLLECTOR_ENDPOINT is set
budget = Budget()                             # AI_MONTHLY_BUDGET_USD, price table from env
limiter = TokenBucket(capacity=10, refill_per_sec=10 / 60)   # 10/min/user, process-local
_triage_service: TriageService | None = None

def get_triage_service() -> TriageService:
    """Lazily built so a missing ANTHROPIC_API_KEY surfaces as 503, not an import error.
    Tests inject a fake through app.state.triage_service."""
    global _triage_service
    injected = getattr(app.state, "triage_service", None)
    if injected is not None: return injected
    if _triage_service is None: _triage_service = TriageService()
    return _triage_service

async def poll_loop():
    source = prometheus if ADAPTER == "prometheus" else simulator
    while True:
        try:
            snap = await source.snapshot()
            snap["ts"] = time.time()
            latest.clear(); latest.update(snap)
            dead = []
            for ws in clients:
                try: await ws.send_text(json.dumps(snap))
                except Exception: dead.append(ws)
            for ws in dead: clients.discard(ws)
        except Exception as e:
            print("poll error:", e)
        await asyncio.sleep(POLL_SECONDS)

@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(poll_loop())
    yield
    task.cancel()

app = FastAPI(title="DC-North AIOps", lifespan=lifespan)

class Incident(BaseModel):
    id: str
    kind: Literal["thermal-zone", "thermal-rack", "cpu", "psu"]
    key: str
    sev: Literal["crit", "warn"]
    title: str
    summary: str
    rca: str
    conf: float
    runbook: Literal["rb-crac", "rb-cpu", "rb-psu", "rb-airflow"]
    opened: str

class LogEntry(BaseModel):
    text: str

@app.websocket("/ws/telemetry")
async def telemetry(ws: WebSocket):
    await ws.accept(); clients.add(ws)
    if latest: await ws.send_text(json.dumps(latest))
    try:
        while True: await ws.receive_text()   # keep-alive; client sends pings
    except WebSocketDisconnect:
        clients.discard(ws)

@app.post("/api/v1/incidents", status_code=201)
@app.post("/api/incidents", status_code=201, deprecated=True)
async def create_incident(inc: Incident, user=Depends(current_user),
                          x_draft_request_id: str | None = Header(default=None),
                          x_draft_fields_changed: str | None = Header(default=None)):
    if inc.id in incidents: raise HTTPException(409, "incident exists")
    rec = inc.model_dump() | {"log": [], "ticket": None, "resolved": False}
    try:
        if TICKETING == "servicenow": rec["ticket"] = await servicenow.create(rec)
        elif TICKETING == "jira":     rec["ticket"] = await jira.create(rec)
    except Exception as e:
        rec["log"].append(f"ticket sync failed: {e}")
    incidents[inc.id] = rec
    # observability-spec §1: `incident.save` is its own trace, linked to the draft by request_id
    # when the console confirms a triage draft (optional headers; the JSON contract is unchanged).
    changed = [f.strip() for f in (x_draft_fields_changed or "").split(",") if f.strip()]
    with tracing.incident_save_span(incident_id=inc.id, draft_request_id=x_draft_request_id,
                                    fields_changed_by_operator=changed):
        pass
    return rec

@app.post("/api/v1/incidents/{inc_id}/log")
@app.post("/api/incidents/{inc_id}/log", deprecated=True)
async def add_log(inc_id: str, entry: LogEntry, user=Depends(current_user)):
    rec = incidents.get(inc_id)
    if not rec: raise HTTPException(404)
    line = f"{entry.text} (by {user['name']})"
    rec["log"].append(line)
    try:
        if rec["ticket"]:
            if TICKETING == "servicenow": await servicenow.comment(rec["ticket"], line)
            elif TICKETING == "jira":     await jira.comment(rec["ticket"], line)
    except Exception as e:
        rec["log"].append(f"ticket sync failed: {e}")
    return rec

@app.post("/api/v1/incidents/{inc_id}/resolve")
@app.post("/api/incidents/{inc_id}/resolve", deprecated=True)
async def resolve(inc_id: str, user=Depends(current_user)):
    rec = incidents.get(inc_id)
    if not rec: raise HTTPException(404)
    if rec["resolved"]: raise HTTPException(409, "already resolved")
    rec["resolved"] = True
    try:
        if rec["ticket"]:
            if TICKETING == "servicenow": await servicenow.resolve(rec["ticket"])
            elif TICKETING == "jira":     await jira.resolve(rec["ticket"])
    except Exception as e:
        rec["log"].append(f"ticket sync failed: {e}")
    return rec

@app.get("/api/v1/incidents")
@app.get("/api/incidents", deprecated=True)
async def list_incidents(user=Depends(current_user)):
    return list(incidents.values())

@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    """api-contract Rev 2 §7: the triage endpoint answers 400 for text too long / history > 19.
    Every other validation failure keeps FastAPI's 422 shape."""
    if request.url.path == "/api/v1/ai/triage":
        for err in exc.errors():
            loc = tuple(err.get("loc", ()))
            if loc == ("body", "text") and err.get("type") == "string_too_long":
                return JSONResponse({"detail": "text too long"}, status_code=400)
            if loc == ("body", "history") and err.get("type") == "too_long":
                return JSONResponse({"detail": "history too long"}, status_code=400)
    return JSONResponse({"detail": jsonable_errors(exc)}, status_code=422)

def jsonable_errors(exc: RequestValidationError) -> list:
    return [{k: (str(v) if k == "ctx" else v) for k, v in e.items() if k != "url"} for e in exc.errors()]

@app.post("/api/v1/ai/triage", response_model=TriageResponse)
async def ai_triage(req: TriageRequest, user=Depends(current_user)):
    """One model call; the reply is a proposal. Only POST /api/incidents writes, after confirmation."""
    request_id = "req_" + secrets.token_hex(8)
    sub_hash = hashlib.sha256(user["sub"].encode()).hexdigest()[:12]
    started = time.monotonic(); status = 500
    with tracing.http_triage_span(request_id=request_id, sub_hash=sub_hash, hall=req.context.hall,
                                  history_len=len(req.history), input_chars=len(req.text)) as span:
        try:
            if not limiter.allow(user["sub"]):
                status = 429; raise HTTPException(429, "rate limited")
            try:
                service = get_triage_service()
            except Exception as e:
                status = 503; tracing.set_attributes(span, {"error": tracing.redact(str(e))})
                raise HTTPException(503, "model unavailable") from None
            try:
                result = await triage_with_budget(service, budget, req, request_id)
            except BudgetExhausted:
                status = 429; raise HTTPException(429, "budget exhausted") from None
            except ModelUnavailable:
                status = 503; raise HTTPException(503, "model unavailable") from None
            except UnusableOutput:
                status = 503; raise HTTPException(503, "unusable model output") from None
            status = 200
            return result.response
        finally:
            tracing.set_attributes(span, {"http.status_code": status,
                                          "latency_ms": round((time.monotonic() - started) * 1000, 1)})

@app.get("/healthz")
async def health(): return {"ok": True, "adapter": ADAPTER, "clients": len(clients), "db": "memory",
                            "tracing": tracing.tracing_status()}

@app.get("/")
async def index(): return FileResponse(os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html"))
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "frontend")), name="static")
