# api-contract-spec.md — DC-North AIOps Console

<!-- Weekend 3, Lecture 5: shared messages. Exact interfaces, flexible internals. -->

Base path `/api/v1` (incident routes also answer at `/api/…` as a deprecated alias until 2026-11-30). JSON throughout. Errors: `{"detail": "<message>"}`; validation errors may carry structured entries from FastAPI.

## 1. Product decisions → contract
| Requirement | Expression in the contract |
|---|---|
| Open an incident the operator can act on | `POST /incidents` returns 201 and the saved Incident with empty `log`. |
| Never open the same incident twice | Duplicate `id` → 409. |
| Every action is attributable | `POST /incidents/{id}/log` appends `"<text> (by <name>)"` using the token's name. |
| Resolution closes the ticket | `POST /incidents/{id}/resolve` → 200 Incident with `resolved: true`; ticket closed if configured. |
| Telemetry has one shape | WebSocket `/ws/telemetry` pushes `Snapshot` only. |
| Liveness for the load balancer | `GET /healthz` → 200 `{ok, adapter, clients, db}`. |

## 2. Schemas
```ts
Rack = { id: "A-01"…"D-06", zone: "A"|"B"|"C"|"D", servers: int ≥ 0,
         powerKw: number, inletC: number, cpu: int 0–100, online: boolean }

Snapshot = { racks: Rack[], itLoadKw: number, pue: number|null, ts: number /* unix s */ }

Incident = { id: string /^INC-\d+$/, kind: "thermal-zone"|"thermal-rack"|"cpu"|"psu",
             key: string /* zone letter or rack id */, sev: "crit"|"warn",
             title: string, summary: string, rca: string, conf: number 0–1,
             runbook: "rb-crac"|"rb-cpu"|"rb-psu"|"rb-airflow",
             opened: string /* ISO-8601, trailing Z */, closed?: string,
             resolved: boolean, ticket: string|null, log: string[] }

LogEntry = { text: string 1–500 chars }
```

## 3. Endpoints
| Method | Path | Auth | Request | Responses |
|---|---|---|---|---|
| GET | `/healthz` | none | — | 200 `{ok:true, adapter, clients, db}` |
| WS | `/ws/telemetry` | none (read-only) | client sends `"ping"` every 15 s | server pushes `Snapshot` on connect and every poll |
| GET | `/incidents` | bearer | — | 200 `Incident[]` |
| POST | `/incidents` | bearer | `Incident` minus `log/resolved/ticket/closed` | 201 `Incident`; 409 duplicate; 422 invalid |
| POST | `/incidents/{id}/log` | bearer | `LogEntry` | 200 `Incident`; 404 unknown id |
| POST | `/incidents/{id}/resolve` | bearer | — | 200 `Incident`; 404; 409 already resolved |

Auth failures: 401 `{"detail":"missing bearer token"}` / `{"detail":"invalid token: …"}`.

## 4. Examples
`POST /incidents`
```json
{"id":"INC-101","kind":"thermal-zone","key":"C","sev":"crit",
 "title":"Zone C thermal excursion",
 "summary":"3 racks in Zone C rose above baseline together (C-01, C-03, C-05).",
 "rca":"CRAC-3 is the only shared cooling dependency for these racks …",
 "conf":0.91,"runbook":"rb-crac","opened":"2026-10-17T15:42:10Z"}
```
→ 201 with `"resolved":false,"ticket":"INC0012345","log":[]`.

## 5. What the contract does not prescribe
Database queries, adapter internals, how the console draws the heatmap, the runbook step cadence.

## 6. Open questions (resolved in review)
- 403 vs 404 for an incident the operator may not see? → All operators see all incidents in one hall; 404 only for unknown ids.
- Should `GET /incidents` filter resolved? → Query `?resolved=false` optional; default returns all.
- Day-level or rack-level telemetry endpoints? → None; the snapshot is the only read path. Prometheus answers history.

---
## Revision 2 (with AI feature) — 2026-10-17
### 7. AI triage endpoint
| Method | Path | Auth | Request | Responses |
|---|---|---|---|---|
| POST | `/ai/triage` | bearer | `TriageRequest` | 200 `TriageResponse`; 400 text too long / history > 19; 401; 429 `{"detail":"rate limited"}` or `{"detail":"budget exhausted"}`; 503 `{"detail":"model unavailable"}` or `{"detail":"unusable model output"}` |
```ts
TriageRequest  = { text: string 1–2000, draft: Draft|null,
                   history: {role:"user"|"assistant", content:string}[] ≤ 19,
                   context: { hall: string, now: string /* ISO Z */ } }
Draft          = { kind: "thermal-zone"|"thermal-rack"|"cpu"|"psu"|"other"|null,
                   key: string|null, sev: "crit"|"warn"|null,
                   summary: string|null, probable_cause: string|null,
                   runbook: "rb-crac"|"rb-cpu"|"rb-psu"|"rb-airflow"|null }
TriageResponse = { draft: Draft, missing_fields: string[], clarification_fields: string[],
                   reply: string, request_id: string, model: string }
```
Invariants: all six `Draft` keys present; `missing_fields ∩ clarification_fields = ∅`; their union equals the null fields among `kind, key, sev`, plus `kind` when `kind` is `"other"` (not catalogued counts as unresolved). The response never includes an incident id. `POST /incidents` is unchanged and remains the only write.
