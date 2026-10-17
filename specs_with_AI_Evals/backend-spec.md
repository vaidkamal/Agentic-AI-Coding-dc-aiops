# backend-spec.md — DC-North AIOps Console

<!-- Weekend 3, Lecture 5: data and rules. The browser can bypass its checks; the server enforces these. -->

## 1. Responsibilities
The backend feeds telemetry, authenticates operators, persists incidents, and syncs tickets. It does **not** run detection in v1 (detection runs in the console against the same contract). It never actuates equipment.

## 2. Tech decisions
| Decision | Chosen | Alternatives | Why |
|---|---|---|---|
| Framework | FastAPI + uvicorn | Flask, Django | Async WebSocket broadcast, Pydantic models give the contract for free. |
| Telemetry source | Adapter pattern: `simulator`, `prometheus` | Direct SNMP, Kafka | Adapters conform to one snapshot shape; the console never adapts to a source. |
| Database | PostgreSQL (cloud), SQLite (local) via SQLAlchemy | In-memory dict | Incidents must survive restart once the backend is the system of record. |
| Auth | OIDC bearer JWT validated against IdP JWKS | Session cookies, API keys | Works with Entra ID / Okta / Keycloak; nothing to store. |
| Ticketing | ServiceNow Table API or Jira Cloud v3, selected by env | Email, Slack | Operators already live in these tools; work notes give the audit trail. |
| Deployment | Docker image; AWS ECS Fargate + RDS via Terraform; GitHub Actions CI/CD | Render, Fly.io | Matches course Phase 4–7; Terraform state tracked. |

## 3. Data model
```
Operator (sub, name, roles)              ← from OIDC token, not stored
Incident (id, kind, key, sev, title, summary, rca, conf, runbook,
          opened_at, closed_at, resolved, ticket_ref, created_by)
IncidentEvent (incident_id, at, actor, text)      ← timeline, append-only
RunbookRun (incident_id, runbook, approved_by, approved_at, step, done)
```
Relationships: an Incident has many IncidentEvents and at most one RunbookRun. Telemetry is not stored by the backend (Prometheus holds history).

## 4. Rules the server enforces
| Rule | Enforcement |
|---|---|
| Incident ids are unique and client-proposed (`INC-nnn`) | 409 on duplicate. |
| `sev` ∈ {crit, warn}; `kind` ∈ {thermal-zone, thermal-rack, cpu, psu}; `conf` ∈ [0,1] | 422 from Pydantic. |
| Only authenticated operators write | 401 without a valid bearer when `AUTH_MODE=oidc`. |
| Runbook approval is an explicit event with an actor | `POST /incidents/{id}/log` text "operator approved runbook …" records actor from token; no endpoint starts a runbook server-side. |
| Resolution is final | `POST /resolve` on a resolved incident returns 409. |
| Ticket sync must not block the operator | Ticket calls have 10 s timeout; failure is logged as an event, request still succeeds. |
| Telemetry snapshot shape is fixed | Adapters validated against the contract; malformed snapshot is dropped and logged, never broadcast. |

## 5. Telemetry poll loop
Every `POLL_SECONDS` (2) the active adapter returns one snapshot; it is broadcast to every WebSocket client and kept as `latest` for new clients. Clients send `"ping"` every 15 s; dead sockets are pruned.

## 6. Authentication
OIDC discovery → JWKS cached 1 h; audience and issuer checked; claims `sub`, `name`, `roles`. `AUTH_MODE=dev` returns a fixed dev operator and is refused when `ENV=production`.

## 7. Secrets and configuration
All from environment: `TELEMETRY_ADAPTER`, `PROM_URL`, `PROM_Q_*`, `AUTH_MODE`, `OIDC_*`, `TICKETING`, `SNOW_*`, `JIRA_*`, `DATABASE_URL`. Nothing in code or in Git. `.env.example` documents every key.

## 8. Deployment and recovery (Phases 4–7)
- Image built in CI, pushed to ECR, ECS service updated; Alembic migration runs as a one-off task before rollout.
- RDS automated backups + manual snapshot before any `terraform destroy`. Restore proof: the same `INC-nnn` with its original `opened_at` is retrievable after rebuild.
- Health: `GET /healthz` → `{ok, adapter, clients, db}`.

## 9. Open questions (resolved in review)
- JWT lifetime? → Set by IdP; backend trusts `exp`. No refresh handling server-side.
- Who may approve runbooks? → Any authenticated operator in v1; role check (`shift-lead`) deferred and recorded.
- Rate limits? → None in v1 (no model calls yet). Added with the AI feature.

---
## Revision 2 (with AI feature) — 2026-10-17
### 10. AI triage service
- Module `backend/ai/`: `triage.py` (one `AsyncAnthropic` call with a declared Pydantic response model), `budget.py` (reserve/settle against `AI_MONTHLY_BUDGET_USD`), `schemas.py`.
- Model: `AI_MODEL` env, default `claude-haiku-4-5-20251001`. `max_tokens=1024`, `timeout=20`, `max_retries=0`.
- The system prompt contains the interpretation rules of AI-spec §4 and the fixed zone↔CRAC mapping. Operator text is placed in the user turn only, delimited, and described as data.
- Post-validation in code: rack-id regex normalisation, zone letter check, `missing_fields ∪ clarification_fields` = set of null fields among kind/key/sev, no field in both lists. Invalid model output → 503, never a partial draft.
- Rate limit: in-process token bucket, 10/min/user keyed by `sub`.
- Budget: estimate cost from usage (`input_tokens`, `output_tokens`, price table in env); reserve an upper bound before the call, settle actual after. Persist month-to-date spend in the SQLite file `AI_BUDGET_DB` until the `DATABASE_URL` store exists (T16), then move it there.
- **No write path.** `backend/ai/` imports nothing from the incident router and exposes nothing that writes. Enforced by AI-6.
- Secrets: `ANTHROPIC_API_KEY` env only; never logged; traces record the model name and token counts, not the key.
### 9. Open questions (added)
- Replica-wide rate limiting? → Deferred; documented as process-local.
- Should the judge run in production? → No; judge is an eval-time tool only (see observability-spec).
