# goal-spec.md — DC-North AIOps Console

<!-- Weekend 3, Lecture 5: scope and success. The architect (me) defines intent; the coding agent drafts; I review. -->

## Goal
A NOC engineer on the Hall 2 floor sees one correlated incident with a probable cause and approves a runbook in one tap, instead of reading 24 separate rack alarms.

## Who needs it
| User | What they must accomplish |
|---|---|
| NOC engineer (primary) | Spot where the problem is within seconds; act on one incident, not many alarms. |
| Shift lead | Approve a remediation runbook and see who did what, when. |
| Capacity planner | Know how many days until hall power reaches the 80 % planning line. |

## The product
A responsive web console for one data-centre hall (Hall 2: 4 zones, 24 racks, 1,200 kW design). It ingests rack telemetry, detects anomalies, correlates them to one probable cause per zone, proposes a catalogued runbook, records an audit trail, forecasts power capacity, and answers operator questions from live state.

## Use cases (MVP)
1. Watch the hall: rack-floor heatmap, site load, PUE, open incident count.
2. Receive an incident: one incident per root cause with cause, evidence and confidence.
3. Approve a runbook: steps execute only after explicit approval; every step is logged.
4. Resolve: incident auto-resolves after five consecutive normal samples; ticket closes.
5. Plan capacity: days-to-80 % power from a regression on the load series.
6. Ask the copilot: hottest rack, PUE, forecast, open incidents, offline racks, what to do next.
7. Verify the detector: inject a CRAC failure, runaway process or PSU loss from the header.

## Boundaries (out of scope for MVP)
- No direct actuation of CRAC, PDU or BMS controllers. Runbooks page people and tools.
- One hall only. No multi-site view.
- No historical reporting beyond the live window (20 samples per rack, 60 site samples).
- No free-text AI feature in this version (added in specs_with_AI_feature/AI-spec.md).

## Constraints
- Single self-contained HTML console, no build step, Chart.js from cdnjs only.
- Python FastAPI backend; PostgreSQL in cloud, SQLite locally.
- OIDC bearer auth on write endpoints when enabled; credentials only from env.
- Refresh ≤ 2 s for 24 racks × 4 metrics at 0.5 Hz without visible jank.
- Mobile-usable at 360 px; follows system light/dark theme.
- Timeline: core journey in one weekend; cloud deployment in the following one.

## Shared vocabulary (glossary)
| Term | Agreed meaning |
|---|---|
| Hall | One machine room; the unit the console shows. Hall 2 here. |
| Zone | A group of six racks sharing one CRAC unit. Zones A–D ↔ CRAC-1…4. |
| Rack | One cabinet, id `Z-NN` (e.g. `B-04`). Holds 18–30 servers. |
| Inlet temperature | Air temperature entering the rack front, °C. ASHRAE A1 recommended max 27 °C. |
| Sample | One telemetry snapshot of all racks, every 2 s. |
| Baseline | Rolling mean and standard deviation of a metric over the last 20 samples. |
| Anomaly | A metric > 3 σ above its baseline, or above an absolute ceiling (27 °C, 92 % CPU). |
| Incident | One record per probable root cause, with evidence, confidence and a proposed runbook. Not an alarm. |
| Runbook | A catalogued ordered list of remediation steps. Runs only after operator approval. |
| PUE | Facility power ÷ IT power. Target ≤ 1.50. |
| Planning line | 80 % of design power (960 kW). Crossing it starts a power upgrade. |

## Success criteria
Initial: "A NOC engineer sees an incident when something goes wrong."

Stronger, testable: Given a CRAC failure injected in Zone C, within 6 s the console shows exactly one open incident for Zone C with a probable cause naming CRAC-3, no per-rack incidents for zone C, and an "Approve runbook: Cooling failover" button; after approval the five steps execute in order and the incident moves to Resolved after five normal samples.

## Observable check of the main journey
1. Open the console; the heatmap shows 24 racks, all blue.
2. Inject "CRAC unit failure (Zone C)". Zone C racks turn orange then red.
3. Incidents badge shows 1. The incident reads "Zone C thermal excursion", confidence 91 %.
4. Approve the runbook. Steps tick off. Fault clears. Incident resolves.
5. Open the timeline: open → approved → complete → resolved, all time-stamped.

## Ambiguities resolved
| What we found | What we decided |
|---|---|
| "Alert" and "incident" used interchangeably in early notes | Alarm/alert = raw threshold signal (input). Incident = correlated record (output). Only incidents are shown. |
| Copilot described as "AI" in the first draft | MVP copilot is rule-based over live state. The model-backed feature is a separate spec. |
| "Runs on a phone" | Responsive web at ≥ 360 px. No native app. |

## Output files
`frontend/index.html`, `backend/app.py`, `backend/auth.py`, `backend/adapters/{simulator,prometheus}.py`, `backend/integrations/{servicenow,jira}.py`, `backend/requirements.txt`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `README.md`.

---
## Revision 2 (with AI feature) — 2026-10-17
- **Scope added:** an operator may describe a symptom in free text (English or Latin-script Hinglish) and receive a structured incident draft for review. See AI-spec.md.
- **Boundary kept:** the model never opens, approves or resolves anything. Saving goes through the existing incident flow after confirmation.
- **Glossary added:** *Draft* — a model-proposed incident with every field editable and no effect until confirmed. *Clarification* — a field the model could not resolve and asks about.
- **Success criterion added:** Given "C-01, C-03 and C-05 all reading 29 °C since 14:10, CRAC-3 compressor alarm", the draft shows kind thermal-zone, key C, severity critical, runbook Cooling failover, no missing fields; confirming opens INC-nnn with those exact values.
- **Output files added:** `backend/ai/{__init__,triage,budget,schemas}.py`, `tests/test_ai_triage.py`.
