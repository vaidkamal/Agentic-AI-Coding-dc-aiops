# DC-North AIOps

**A spec-driven, agentic-AI-built operations console for a data-centre hall: one correlated incident instead of 24 alarms, a probable cause with confidence, and a runbook the operator approves in one tap. Extended with a bounded AI triage feature (the model proposes; the application saves), evaluated with a golden set and traced in Phoenix, and deployable with backup-and-restore proof.**

Final project for *Agentic AI Coding: From Specification to Deployment* (Prof. Deepak N. Subramani, CDS / QUEST Lab, IISc Bengaluru; CCE Sept–Oct 2026 cohort).

| | |
|---|---|
| Deployed console (Project submission URL) | https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/frontend/ |
| Session transcript (turn by turn) | https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/transcripts/dc-aiops_turn_by_turn.html |
| Session log (by stage) | https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/transcripts/dc-aiops_session_log.html |
| Design decision walkthrough and interview preparation | https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/docs/dc-aiops-design-walkthrough.html |
| Architecture (C4, request paths, failure table) | https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/dc-aiops-architecture.html |
| Source code | https://github.com/vaidkamal/Agentic-AI-Coding-dc-aiops |

## 1. The problem and the setting

**Context.** The console is built for a private, single-tenant data-centre hall: Hall 2, 4 zones, 24 racks, 1,200 kW of design power, owned and operated by one organisation. It is not a public-cloud region.

**The problem.** Operators watch inlet temperature, CPU, PDU power and host availability on separate screens. When a CRAC unit degrades, all six racks in its zone alarm at once; root cause takes hours because nobody correlates the alarms, and the "fix" is a page to facilities after the damage is done.

**Why a private data centre.**
- The ops team sees raw rack-level alarms directly; a hyperscaler hides that layer behind its own tooling.
- The same organisation owns the sensors, the CRAC and PDU units, the management network and the ticketing system, so the authority boundaries from the course (no write path from the model, no actuation, approval with a named operator) can be enforced end to end and verified by a firewall review.
- A small team covers facilities and IT, so the blast radius of a wrong cooling or power action is the whole hall; the system must advise, never act.
- Telemetry and incidents stay inside the organisation; the only optional external call is the bounded AI triage, switched off by leaving the key unset.
- The site has change control, so the phased rollout (replay → shadow → one zone → full hall) can run under its own tickets with rollback by configuration.

**Benefits for the site.**
| Benefit | How |
|---|---|
| One incident per root cause instead of 24 alarms | Zone correlation on the hall's real topology (six racks per CRAC) |
| A probable cause with a confidence number | Rule-based cause and evidence on every incident |
| Fix approved in one tap, fully audited | Approval-gated runbooks; every step logged with the operator's name and mirrored as ticket work notes |
| Capacity planned ahead | Days to the 80 % planning line from the same telemetry |
| Faster triage on the night shift | Free-text note in English or Hinglish → structured draft; the model only proposes, the operator's confirm is the only write |
| Thresholds are the site's own | ASHRAE A1 27 °C, 92 % CPU, 20-sample baseline, tuned on replay data before go-live |
| Low cost, no lock-in | A container, a database, Prometheus; AI spend budget-capped |

**Status.** Validated on simulated telemetry and fault injection; the phased production rollout (§12) and the four open items with their blockers (§11) are stated below.

## 2. What was built

**Console** (`frontend/index.html`, one self-contained file)
- Rack-floor heatmap, site load and PUE, KPIs, per-rack time series.
- Anomaly detection: rolling z-score (window 20) per metric plus absolute ceilings (27 °C per ASHRAE A1, 92 % CPU).
- Zone correlation: three or more racks rising together → **one** CRAC incident; per-rack alarms suppressed.
- Incidents carry probable cause, evidence and a confidence number; runbooks execute only after an explicit **Approve**; every step is logged with the actor; auto-resolve after five normal samples.
- Capacity forecast (least-squares regression → days to the 80 % planning line), rule-based copilot, three injectable faults for verification.
- **Triage tab**: type what you see ("C-01, C-03 and C-05 all at 29 °C since 14:10, CRAC-3 alarm") → structured draft → review, edit, confirm → incident.

**Backend** (`backend/`, FastAPI)
- Telemetry adapters (simulator, Prometheus with overridable PromQL) broadcasting one fixed snapshot shape over WebSocket.
- OIDC bearer auth (JWKS), incident API with timeline, ServiceNow / Jira ticket sync with work notes.
- `ai/`: one Anthropic call with a declared response model, post-validation and rack-id normalisation, 20 s timeout, 1,024-token cap, no retries, per-user rate limit, monthly budget reserve/settle, OpenTelemetry → Phoenix tracing with redaction. **No import path from `ai/` to anything that writes**; a test guards it.

**Evaluation** (`evals/`): golden set T1–T8 chosen by dimension (zone vs rack, typo ids, vague, Hinglish correction, pasted log, below threshold, prompt injection); deterministic checks with pass / fail / unable_to_assess / budget_blocked; judge rubric for the two semantic criteria; codebook v1; mocked baseline (live run asks for budget approval).

**Deployment** (`deploy/`, `.github/workflows/`): CI on every push; deploy on main via GitHub OIDC → ECR → one-off migration task → ECS Fargate → smoke test; Terraform for VPC, ALB, ECS, RDS, ECR, Secrets Manager, CloudFront; `backup.sh` → `destroy.sh` (aborts if the snapshot fails) → `restore.sh` (greps the API for a known `INC-nnn`); Cloudflare Quick Tunnel script for a temporary public demo.

## 3. How it was built: the course method, weekend by weekend

| Weekend | Method | Artefact in this repo |
|---|---|---|
| 1 · Agents | Agent loop, harness, blast radius sets oversight, stop caps | Principles in `CLAUDE.md` (approval gate, bounded calls) |
| 2 · SDD | Spec → Plan → Implement → Verify → Iterate; four control surfaces; "a criterion is a sentence with a command attached"; test the test | `CLAUDE.md`, `.claude/settings.json`, `scripts/verify.sh`, `docs/test-the-test.md` |
| 3 · Specs | `goal` · `frontend` · `backend` · `api-contract`; implementation plan with evidence of completion; fifth spec `AI-spec.md`; minimal viable agent | `specs/`, `specs_with_AI_feature/` |
| 4 · Test & deploy | AC → check mapping; CI; phases 4–7; backup before destroy; restore proof | `backend/tests/`, `.github/workflows/`, `deploy/` |
| 5 · Evals | Observability spec + runbook; test prompts by dimension; open/axial coding → codebook; evaluators; golden set; judge calibration | `specs_with_AI_Evals/`, `evals/` |
| 6 · Design | C4; one complete request; testable failure table; does-it-need-AI / workflow-or-agent flowcharts; ADRs; "keep ownership" | `dc-aiops-architecture.html`, `docs/design-decisions.md`, `docs/interview-questions.md` |

The three `specs*` folders are snapshots, as in the course reference project: the four specs, then the four plus the AI spec with revision-2 sections, then everything plus observability and evaluation.

## 4. Repository map

```
CLAUDE.md                     instructions the coding agent reads every session
.claude/settings.json         agent may run verify/pytest; may not edit specs or the checks
specs/                        goal · frontend · backend · api-contract · implementation-plan (phases 0–9)
specs_with_AI_feature/        + AI-spec.md; revision-2 sections appended to the four specs
specs_with_AI_Evals/          + observability-spec · observability-runbook · ai-implementation-plan
backend/                      app.py · auth.py · adapters/ · integrations/ · ai/ · tests/ (73 tests)
frontend/index.html           the console
evals/                        golden/cases.json · run_cases.py · codebook.md · judge_rubric.md · review-table.md · baseline.md
scripts/verify.sh             definition of done
deploy/                       terraform/ · scripts/ · deployment-brief.md · runbook-release.md · production-rollout.md
.github/workflows/            ci.yml · deploy.yml
docs/                         architecture.md · design-decisions.md (12 ADRs) · interview-questions.md · OPEN-QUESTIONS.md · test-the-test.md
transcripts/                  session log + link to the raw session
dc-aiops-architecture.html    architecture page (GitHub Pages)
index.html                    GitHub Pages landing page
```

## 5. Architecture

Full version with diagrams: [`docs/architecture.md`](docs/architecture.md) (Markdown, renders on GitHub) and the [HTML page](https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/dc-aiops-architecture.html). Decisions: [`docs/design-decisions.md`](docs/design-decisions.md).

```mermaid
flowchart LR
  OP[NOC engineer] -->|watches, approves| CON[Console<br/>heatmap · detector · correlator · runbooks · triage UI]
  CON <-->|WebSocket snapshots / REST| BE[Backend FastAPI<br/>adapters · auth · incidents · ticket sync · ai/triage]
  PROM[Prometheus<br/>node · PDU · env] --> BE
  BE --> PG[(PostgreSQL)]
  BE --> TKT[ServiceNow / Jira]
  BE --> IDP[OIDC IdP]
  BE -. one bounded call .-> LLM[Model API]
```

| Layer | Responsibility | Owns |
|---|---|---|
| Console (`frontend/index.html`) | Floor heatmap, z-score detection, zone correlation, runbook catalogue, triage draft review | Detection logic, the Approve button |
| Backend (`backend/`) | Telemetry adapters → one snapshot shape; OIDC; incident API with timeline; ticket sync; `/ai/triage` with rate limit, budget, tracing | Every write and every model call |
| Database | Incidents, events, runbook runs, AI spend (in-memory in the POC, PostgreSQL in production) | The incident record |
| Prometheus | Telemetry history | — |

Two request paths matter. **Telemetry → runbook:** adapter → broadcast → detect → correlate (≥ 3 hot racks in a zone = one CRAC incident) → `POST /incidents` → operator approves → steps page people and tools → auto-resolve after 5 normal samples. **Free-text triage → incident:** `POST /ai/triage` returns a draft and no permission to write → operator edits and confirms → `POST /incidents` with the exact reviewed fields; the model is not called at that step and a test proves the AI module cannot reach the write path.

Authority: any authenticated operator may open, note and resolve; approving a runbook is logged with the actor (role restriction planned for production); nobody — human or model — can actuate cooling or power, because no such endpoint exists.

## 6. Run it

```bash
cp .env.example .env            # simulator, dev auth, no ticketing, no AI key needed for the console
docker compose up --build       # http://localhost:8080
./scripts/verify.sh             # ruff · 73 tests · evals --mock · no-write-path grep · CDN hosts → GREEN
```
Try it: Inject fault → "CRAC unit failure (Zone C)" → Incidents tab shows one incident → Approve runbook → watch it resolve. Then open Triage and type a symptom.

AI triage needs `ANTHROPIC_API_KEY`; evals: `python evals/run_cases.py --mock` (free) or `--live` (asks for budget approval first). Observability: `pip install arize-phoenix && phoenix serve`, set `PHOENIX_COLLECTOR_ENDPOINT`.

Deployment: `deploy/deployment-brief.md` (services, permissions, cost drivers, what survives teardown) and `deploy/runbook-release.md`.

Taking it to a real hall: `deploy/production-rollout.md` (readiness assessment, what the DC must provide, configuration, on-prem and AWS profiles, five-phase rollout with exit criteria, go-live checklist).

## 7. User guide: the published pages

### 7.1 The console — https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/frontend/
**Purpose.** The operator's single screen for one hall: see where the problem is, get one incident per cause, approve the fix, watch it resolve. On GitHub Pages it runs on the built-in simulator (24 racks, randomised telemetry); with the backend it shows live data. Everything below works identically in both.

| Element | What it shows | What you do with it |
|---|---|---|
| **Header** | Hall name, capacity, live clock | **Inject fault** menu: CRAC unit failure (Zone C), runaway process (B-04), PSU feed loss (D-02). This is how you exercise the system on simulated data; it is not used on live equipment. |
| **KPI row** | IT load (kW and % of 1,200 kW design), PUE against the 1.50 target, average inlet temperature vs ASHRAE A1, servers online, open incidents | Read at a glance; red/green sub-labels say whether each is inside its target. |
| **Rack floor** | 4 zones × 6 racks, each tile coloured by inlet temperature (blue < 20 °C … red > 30 °C), offline racks greyed | Tap a rack to open its time series. A hot zone is visible before you read a number. |
| **Rack panel** | Inlet temperature and CPU for the selected rack over the last 20 samples; servers, power, CPU | Confirm whether one rack or a whole zone is rising. |
| **AI insights** | One line per open incident with its probable cause; the warmest rack when nothing is open; a warning when power will reach 80 % of design within 60 days | Decide where to look first. |
| **Site chart** | IT load and PUE over the last two minutes | Spot a hall-wide drift. |

**The three fault injections (header menu).** Each makes the simulated hall misbehave in one specific way so detection, correlation, approval and resolution can be watched without touching equipment. After choosing one, the menu resets and a toast confirms the injection.

| Option | Simulates | What you see | Proves |
|---|---|---|---|
| CRAC unit failure (Zone C) | The cooling unit for Zone C stops; all six racks warm together (~1 °C per 1.5 s) | Zone C tiles go orange then red; after three hot samples **one** incident "Zone C thermal excursion" (critical, 91 %), no per-rack alarms; runbook *Cooling failover* | Zone correlation: many racks, one cause, one incident |
| Runaway process (rack B-04) | One rack's CPU pins at ~97 % and its power rises | Incident "B-04 sustained CPU saturation" (warning, 84 %), cause "load is rack-local and power tracks it"; runbook *Contain runaway workload* | Single-rack path; 92 % CPU ceiling |
| PSU feed loss (rack D-02) | Rack D-02 loses power: 0 kW, all hosts stop reporting | Tile greyed and struck through; "servers online" KPI drops; after two samples incident "D-02 lost power — N servers offline" (critical, 88 %); runbook *Restore rack power* | Offline detection and the critical path |

Approve the proposed runbook; when its last step completes the fault clears, metrics return to normal, and after five normal samples the incident resolves. One full cycle takes about a minute. On a real hall this menu does not exist; validation uses replayed historical data (rollout phase P1).

**Site IT load and PUE (Overview chart).** *IT load* is the power drawn by the computing equipment, the sum of all rack PDUs in kW, against the 1,200 kW design; it also feeds the capacity forecast. *PUE* (Power Usage Effectiveness) is total facility power ÷ IT power; 1.0 would be perfect, enterprise halls run 1.4–1.8, the target here is 1.50. They share one chart because they move together: when racks run hot the CRAC units work harder, facility power rises while IT power does not, and PUE climbs. Rising load with flat PUE means more useful work; flat load with rising PUE means energy going into cooling trouble. On a real site PUE needs a facility-power meter (`PROM_Q_FACILITY`); without one the console shows it as unavailable rather than inventing a value.

**Heatmap legend.** Six bands: blue < 20 °C · light blue 20–24 · amber 24–27 · orange 27–30 · red > 30 °C · grey = offline. Tiles above 27 °C switch to white text; the selected rack has a blue outline. Zone headers show the CRAC unit each zone depends on (A → CRAC-1 … D → CRAC-4).

**KPI sub-labels.** Each tile carries a one-line judgement under the number: IT load "n % of design" (red above 80 %); PUE "within target" / "above 1.5 target"; Avg inlet "ASHRAE A1 ok" / "trending warm" (above 24 °C); Servers online "all reporting" / "n unreachable"; Open incidents "nothing open" / "n critical".

**AI insights panel.** Up to three kinds of line: one per open incident (id, title, probable cause, striped by severity); "<rack> is warmest at n °C, below alert threshold" when nothing is open and a rack is above 24 °C; "Power reaches 80 % of design in ~n days" when the forecast is under 60 days (amber under 30). When there is nothing to say it says "Hall 2 is healthy" and suggests injecting a fault.

**Incidents tab.**
| Element | Meaning | Action |
|---|---|---|
| Open incidents / Resolved panels | Open ones first, critical on top with a red left stripe, warnings with amber; resolved ones below, faded | — |
| Card header | `INC-nnn` and title; pill *critical* / *warning* / *resolved* | — |
| Meta line | "opened hh:mm:ss" and, once closed, "closed hh:mm:ss" | — |
| Evidence line | What was measured: racks involved, °C above baseline, CPU %, kW change | Read before approving |
| Probable cause box | Plain-language cause and a confidence bar with the percentage (91 % zone thermal, 88 % PSU, 84 % rack CPU, 62 % single hot rack) | Decide whether the cause is plausible |
| **Approve runbook: <name>** | Starts the catalogued steps. Button text changes to "Running…" (disabled) and finally "Runbook complete" | The only way a runbook runs |
| **Acknowledge** | Records "acknowledged by operator" in the timeline and the ticket; nothing else changes | Use when you have seen it but are not acting yet |
| Steps list (after approval) | ✓ done · ▶ current · ○ pending, one step every 1.4 s in the simulator | Watch progress |
| Timeline (collapsed) | Every event with timestamp: opened by detector (confidence), acknowledged, approved "<runbook>", runbook complete, auto-resolved after 5 normal samples | Audit trail; mirrored as ticket work notes when ticketing is on |
| Empty states | "No open incidents. Everything is within baseline." / "Nothing resolved yet this session." | — |

**Capacity tab.**
| Element | Meaning |
|---|---|
| Power used | IT load as % of 1,200 kW, with "n of 1,200 kW" |
| Rack space used | Occupied U as % of 24 racks × 32 U |
| To 80 % power | Days until the 960 kW planning line; "order upgrade now" under 30 days, "comfortable" otherwise; "—" if load is not growing |
| Growth per day | Slope of the least-squares regression on the load series, kW/day |
| Chart | Solid line observed kW (the last 60 samples treated as 60 days), dashed line 30-day forecast, thin red line at 80 % |
| Rack inventory table | Rack, zone, servers, load kW, inlet °C, CPU %, status pill: *normal* / *hot* (> 27 °C) / *saturated* (> 92 % CPU) / *offline* |

**Runbooks tab.** The catalogue; each entry shows a pill *idle* or *proposed for INC-nnn* and its ordered steps. Steps page people and tools; none actuates equipment.
| Runbook | Proposed for | Steps |
|---|---|---|
| Cooling failover | Zone thermal incident | Confirm CRAC supply-air temp and compressor status → Raise setpoint on redundant CRAC by −2 °C → Shift fan speed to 100 % on adjacent units → Page facilities tech with unit id → Verify zone inlet temps return < 25 °C |
| Contain runaway workload | Rack CPU incident | Identify top process on affected hosts → Throttle via cgroup to 60 % CPU → Notify workload owner → Migrate stateless pods to Zone A spare capacity → Confirm CPU < 80 % for 5 samples |
| Restore rack power | Rack PSU incident | Check A-feed breaker state on PDU → Fail hosts to B-feed where dual-corded → Dispatch on-site engineer → Power-on sequence with 10 s stagger → Confirm all hosts reporting |
| Airflow check | Single hot rack | Inspect blanking panels and cable cut-outs → Verify perforated tile placement → Re-check inlet temp after 2 minutes |

**Ops copilot tab.** A question box, an **Ask** button (Enter also works) and five chips: *hottest rack*, *power forecast*, *open incidents*, *PUE*, *what next*. Answers are computed from the live state by keyword, not by a language model, so they cannot invent a rack:
| You ask about | You get |
|---|---|
| hot / temperature / warm | Warmest rack, its zone and CRAC, hall average inlet |
| PUE / efficiency | Current PUE, the 1.50 target, why it rises when racks run hot |
| power / forecast / capacity / growth | IT load, % of design, kW/day, days to the 80 % line |
| incident / alert / open | Each open incident with severity and cause, or "no open incidents" |
| CPU / load / busy | Highest-CPU rack and whether it is in saturation territory |
| offline / down / unreachable | Offline racks and unreachable server count, or "all 24 racks online" |
| next / do / should / recommend | The first open incident and its runbook to approve; otherwise the capacity risk or an airflow check |
| anything else | A list of what it can answer |

**Triage tab (AI feature).**
| Element | Options / behaviour |
|---|---|
| "Describe what you see" text area | Up to 2,000 characters; English or Latin-script Hinglish; pasted alarm lines are fine and are treated as data, never as instructions |
| **Send** | Calls the model once; shows "Thinking…" while waiting; the counter "n of 19" tracks messages in this conversation; at 19 Send is disabled and you finish manually or start over |
| **Start over** | Clears conversation, draft and stored draft |
| Conversation history | Your messages right-aligned (blue), model replies left-aligned (grey) |
| Reply bubble | The model's one-line explanation or its question for a field it could not resolve |
| Draft form — Kind | thermal-zone · thermal-rack · cpu · psu · other · — |
| Draft form — Key | Zone letter (A–D) or rack id `Z-NN`; typos like `D-2` are normalised to `D-02` |
| Draft form — Severity | critical · warning · — |
| Draft form — Runbook | Cooling failover · Contain runaway workload · Restore rack power · Airflow check · — |
| Draft form — Summary, Probable cause | Free text; the summary keeps your timestamps and device names verbatim |
| Field highlighting and flags | Fields the model left empty are outlined amber; the line above the form lists "missing: …" and "needs clarification: …" |
| **Confirm and open incident** | Enabled only when kind (not *other*), key and severity are set **and** you have reviewed the draft (sent or edited); creates the incident exactly as the form shows and jumps to Incidents |
| **Edit manually** | Skip the model: fill kind, key and severity yourself and confirm |
| Messages you may see | "Triage unavailable — draft kept" (model unreachable; edit manually); "rate limited" / "budget exhausted" (429; manual path still works); "The save response never arrived — the incident may already exist. Check the Incidents tab before retrying." (never auto-retried); "Restored an unfinished draft. Review it before confirming." (after a reload); on GitHub Pages: "No backend reachable (published demo). Use Edit manually." |
| What the model can never do | Open, approve or resolve anything. Only Confirm writes, and it sends the exact reviewed fields plus a header linking the save to the model's request id for the audit trace |

**Spec tab.** Read-only: the original problem, goal, user stories, acceptance criteria and the five-stage plan the console was first built from. For auditors; nothing to operate.

**Notifications (toasts).** Short messages at the bottom of the screen: "Fault injected: …", "INC-nnn opened: …", "Running <runbook>", "INC-nnn acknowledged", "INC-nnn resolved", "INC-nnn opened from triage", "Live telemetry connected", "Feed lost — using simulator", "Triage unavailable — draft kept".

**Behaviour you can rely on.** The last tab you used is remembered on reload; the page follows the system light/dark theme; it works at phone width (zones wrap to two per row); the pulse dot next to the clock stops animating when the OS asks for reduced motion.

**Walk-through for a first-time user (two minutes).** Overview → Inject fault → "CRAC unit failure (Zone C)" → watch Zone C tiles turn orange then red → Incidents badge shows 1 → open it, read the cause ("CRAC-3 is the only shared cooling dependency…") → Approve runbook → steps tick → tiles cool → incident moves to Resolved → expand Timeline. Then open Triage and type a symptom.

### 7.2 The session transcript, turn by turn — https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/transcripts/dc-aiops_turn_by_turn.html
**Purpose.** The course asks for an export of the turn-by-turn conversation so a reviewer can see how the project was built, not only what came out. This page lists all 41 architect messages verbatim, in order, across the two sessions (7 and 17 October 2026); under each one the harness's response is condensed to what was decided, built and delivered, with the files produced. Attached images and PDFs are described in brackets. Blue = architect, green = harness. The raw harness session (sign-in required) is linked at the top for anyone who wants the unedited record.

### 7.2a The session log, by stage — https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/transcripts/dc-aiops_session_log.html
**Purpose.** The same work grouped into the course's stages rather than by message, for a reader who wants the shape of the build without the back-and-forth. Colour-coded: blue = architect instruction, green = what the harness produced, amber = a review or an incident. It records: the first specification and console (turn 1); backend, adapters and integrations (turn 2); the review that found the spec living only inside the app and the spec files that followed (turn 3); the submission form (turn 4); and the rebuild to the trainer's method (turn 5): the six-weekend extraction, the four specs, the fifth AI spec, the evals-stage documents, the workspace-recycling incident and the lesson "commit after every turn", the two parallel builders, and the eleven conflicts they reported with the decision taken on each.

### 7.3 The design-decision walkthrough — https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/docs/dc-aiops-design-walkthrough.html
**Purpose.** The course's "design decision walkthrough and interview preparation": why the system is the way it is, and the questions I prepared to answer without opening the code. Sections: (1) how the project was built, weekend by weekend, with the repository layout; (2) the design decisions, each with what was chosen, what was rejected and why (detection method, correlate-before-alarm, approval gate, explainable incidents, detection in the browser, one telemetry contract, announced feed loss, one bounded model call, model-proposes/application-saves, limits in code, observability, golden set first, deployment with recovery proof); (3) three trade-offs I would defend; (4) how it was verified, criterion by criterion; (5) interview preparation: the eight questions I expect most, with answers; (6) what remains, honestly. The full decision records with revisit-when conditions are `docs/design-decisions.md`; the 25 interview questions are `docs/interview-questions.md`.

### 7.4 The architecture page — https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/dc-aiops-architecture.html
C4 context, containers and components; the two request paths (telemetry → runbook, free-text → incident); the testable failure table; who may do what; where authoritative information lives; the deployment view. Markdown twin: `docs/architecture.md`.

## 8. Verification evidence

| Requirement | Check | Result |
|---|---|---|
| Goal-spec success criterion | Inject CRAC failure; walk the journey | One Zone C incident, 91 % confidence, resolved after 5 normal samples |
| API contract | `pytest tests/test_api.py` | 9 passed (201/409/404/409-on-resolved/401, enums → 422, deprecated alias) |
| AI-1…AI-8 | `pytest tests/test_ai_triage.py` (frozen fixtures) | 33 passed; write-path mutation turns it red |
| OBS-1…OBS-3 | `pytest tests/test_tracing.py` | 10 passed |
| Golden set T1–T8 | `python evals/run_cases.py --mock` | 0 failures / 8 assessed (mocked) |
| Test the test | three deliberate faults | each went red, then green on restore |
| OBS-1…OBS-3 against a running Phoenix | fake model through the real endpoint, 8 cases + 1 confirm | 8 traces with the specified spans; `incident.save` linked by request id; no secrets exported (§9) |
| Deployment scaffold | `bash -n`, YAML parse, `tofu fmt`, HCL reference check | clean; `terraform validate` and apply pending an AWS account |

## 9. Observability and evaluation: designed, integrated, demonstrated

### 8.1 Observability (what the system records about itself)
Specified in [`specs_with_AI_Evals/observability-spec.md`](specs_with_AI_Evals/observability-spec.md), implemented in `backend/ai/tracing.py`, exercised by 10 tests, and **demonstrated against a running Arize Phoenix** on 2026-10-17.

Every `POST /api/v1/ai/triage` produces one OpenTelemetry trace: `http POST /api/v1/ai/triage` → `budget.reserve` → `anthropic.triage` (model, `prompt_version`, `rules_version`, sanitised input, output draft, token usage) → `triage.validate` (id normalisation, rejection reason) → `budget.settle`. When the operator confirms, a separate `incident.save` trace is linked by `request_id` and records which fields the operator changed. API key and bearer are redacted; operator identity is hashed. With no collector configured, tracing is a no-op and `/healthz` reports `tracing: off` so the gap stays visible.

![Phoenix trace of one triage call](evals/results/phoenix-trace-detail-20261017.png)

Evidence from the Phoenix run (`evals/results/`): 8 traces with the spans above; one `incident.save` span with `incident_id=INC-501`, `draft_request_id` = T1's request id, `fields_changed_by_operator=["probable_cause"]`; no secret in any exported attribute (`phoenix-traces-mockmodel-20261017.json`). The run also kept 16 earlier traces whose `error` attribute (`TypeError …`) exposed a mis-built fake client in the launcher while the endpoint correctly answered 503, which is the observability design finding a fault in its own builder.

### 8.2 Evaluation (how the AI feature is judged)
The course loop: analyse traces → write one note per observation → group into a codebook → turn categories into checks → improve one change at a time. Artefacts: golden set [`evals/golden/cases.json`](evals/golden/cases.json) (T1–T8 chosen by dimension: zone vs rack, typo ids, vague, Hinglish correction, pasted log, below threshold, injection), runner [`evals/run_cases.py`](evals/run_cases.py) (`--mock` free in CI; `--live` prints the estimate and asks for approval), [`codebook.md`](evals/codebook.md) v1, [`judge_rubric.md`](evals/judge_rubric.md) for the two semantic criteria, [`review-table.md`](evals/review-table.md), [`baseline.md`](evals/baseline.md). Verdict vocabulary: pass / fail / unable_to_assess / not_applicable / budget_blocked.

| Run | Model | Result | Establishes |
|---|---|---|---|
| `run_cases.py --mock` (CI, every push) | canned outputs | 8/8 pass | Checking logic, invariants, bounds, budget wrapper, no-write-path guard |
| Endpoint run through Phoenix (2026-10-17) | fake client injected into the real backend | 8/8 pass, 9 traces exported | Contract, tracing and the confirm linkage end to end over HTTP |
| `run_cases.py --live` | real model | **pending** (≈ US$0.06) | The model's behaviour; then open/axial coding on real traces, one hill-climb round, model/effort comparison |

What the fake-model runs do not establish is anything about the real model; the live baseline is item 2 in §11.

## 10. What I learned

1. **The spec is the contract, and it must be a file.** My first package shipped with the spec living inside a tab of the app. The next engineer could not open it. Nothing was "spec-driven" until `specs/` existed.
2. **A criterion is a sentence with a command attached.** "Works on mobile" is a hope; "no horizontal scroll at 360 px" and `pytest -k bounds` are criteria. Every acceptance criterion in `AI-spec.md` names its command.
3. **Fix the spec first.** The builders found eleven places where the documents and the code disagreed (base path, `kind: "other"` versus the null-field invariant, where budget is stored, six spans versus five plus one). Each got a decision, the affected documents were updated, and only then the code. The list is in `docs/OPEN-QUESTIONS.md`.
4. **Authority lives outside the model.** The triage model returns a proposal and no permission to write. The single write endpoint is called only after the operator confirms the exact fields. A test asserts the AI module cannot reach it; I broke it on purpose to see the test go red.
5. **The minimal viable agent is usually not an agent.** The two Weekend 6 flowcharts led to one model call with structured output. The condition for adding a tool is written in the ADR, so the decision can be revisited with evidence rather than enthusiasm.
6. **Test the test.** Three deliberate faults, each turned a check red. A green suite is only evidence once you know it can fail.
7. **Evaluation is a habit, not a score.** Eight cases reveal failure kinds; they do not estimate production frequency. Mocked checks protect logic in CI; live runs with budget approval test behaviour; the judge is a tool to apply the expert's rule at scale, not a replacement for it.
8. **A "done" label needs evidence.** Phase 7 (restore proof) is marked *blocked* in the plan because incidents are in-memory today. Saying so is worth more than a green row.
9. **Commit after every turn.** The cloud workspace was recycled between sessions and the code had to be recreated from the session record. Git is the memory the harness does not have.
10. **Keep ownership.** I can explain the request path, who may change data, what happens when the provider is slow or wrong, and why each choice was made. That, not the line count, is what the agentic workflow delivers.

## 11. What remains

Everything above this line has evidence; everything below has a plan and a named blocker.

| # | Work | Why it is open | Blocker | How to finish | Evidence of completion |
|---|---|---|---|---|---|
| 1 | **T16 — persist incidents to PostgreSQL** | The backend keeps incidents in a Python dict; a restart loses them and the ticket is the only durable copy. backend-spec requires PostgreSQL. Until then Phase 7 (backup → destroy → rebuild → same `INC-nnn` returns) cannot be proven, so the plan marks it *blocked*, not *done*. | Code only | Add SQLAlchemy + Alembic; tables `incidents`, `incident_events`, `runbook_runs`, `ai_spend`; `DATABASE_URL` from env (SQLite local, RDS cloud); replace the dict with repository functions; API contract unchanged; add a restart test. | `docker compose down && up` → `GET /api/v1/incidents` still returns the incident; contract tests stay green. |
| 2 | **Phase 9.6b — live evaluation** | T1–T8 have only run in mock mode, which proves the checking logic, not the model's behaviour. | `ANTHROPIC_API_KEY` (≈ US$0.06 for 8 calls) | `phoenix serve`; set `PHOENIX_COLLECTOR_ENDPOINT`; `python evals/run_cases.py --live` (asks for `y`); then runbook §C–H: one Phoenix note per observation (open coding), group into the codebook (axial coding), one hill-climb round on the prompt's rules section, model/effort comparison, keep the cheapest config that still passes. | `evals/baseline.md` replaced by live results with Phoenix links; `ai-implementation-plan.md` rows 9.6b–9.8 dated done. |
| 3 | **Phases 4–6 — deploy to AWS** | Terraform, deploy workflow and backup/restore scripts are written and syntax-checked; nothing exists in a cloud account yet. | AWS account (≈ US$75/month while running) | One-time S3 + DynamoDB state bootstrap (`deploy/terraform/backend.tf`); GitHub secrets `AWS_DEPLOY_ROLE_ARN`, `ALB_URL`, `SMOKE_TOKEN`; `terraform init/plan/apply`; push to `main`; point the console at the CloudFront URL; with T16 done run `backup.sh` → `destroy.sh` → `restore.sh INC-nnn`; destroy again so nothing is left running. Demo fallback: `deploy/scripts/demo-tunnel.sh`. | Phase 4: drift-free apply, ALB answers 503. Phase 5: `/healthz` 200 on the ALB, smoke incident created and resolved. Phase 6: incident created from the hosted page. Phase 7: `restore.sh` prints PASS. |
| 4 | **CRAC supply-temperature series** | The zone rule infers a CRAC failure indirectly (≥ 3 racks hot together). The CRAC itself is not measured, so confidence stays at 0.91 and a rack-level CPU incident is masked during a zone excursion (ADR-02 revisit-when). | Real sensors; simulator version is code only | Spec first: add `crac` to the snapshot contract (`supplyC`, `compressor: on/off/alarm` per zone) and a rule row (zone incident on ≥ 3 hot racks *or* CRAC alarm + ≥ 1 hot rack; confidence 0.97 when evidence agrees); simulator emits it and the fault injection flips the alarm; `PROM_Q_CRAC` in the adapter; console shows it in the zone header and the incident evidence line. | Inject CRAC failure → incident opens on the first hot rack plus the alarm with the higher confidence; a single hot rack without an alarm still opens only a rack-level warning. |

Items 1 and 4 need only code; items 2 and 3 need the API key and the AWS account.

## 12. Production rollout: from POC to a live hall

Full guide: [`deploy/production-rollout.md`](deploy/production-rollout.md). The POC proves the design and the method; the steps below are how to earn the evidence in a real data centre, one bounded step at a time. The rule throughout: **observe and advise before paging anyone; never actuate equipment.**

### 10.1 Readiness gaps to close first
| Area | POC | Production needs |
|---|---|---|
| Incident store | In-memory | PostgreSQL with backups (T16) |
| Detection | In each browser | One backend worker per hall so all operators see the same incidents |
| Runbooks | Steps simulated in the console | Steps that page people / create tasks through real integrations |
| Authorisation | Any operator approves | Role `dc-shift-lead` required to approve |
| Telemetry | Sample PromQL | Site exporters labelled `rack`,`zone`; CRAC supply temperature and compressor state |
| Network | — | Management network only; firewall review proving no path to BMS/PDU write interfaces |

### 10.2 What the data centre provides
Inlet temperature per rack (environmental probes via BMS/DCIM or SNMP), CPU per host (`node_exporter`), power per rack (intelligent PDUs via `snmp_exporter`), host up/down, facility power for PUE, CRAC state from the BMS; an OIDC app with `roles` claim; a ticketing service account; a named owner (shift lead) and a facilities contact.

### 10.3 Configuration
Everything by environment from a secret manager (`.env.example` lists every key): `ENV=production`, `TELEMETRY_ADAPTER=prometheus` with site-validated `PROM_Q_*`, `AUTH_MODE=oidc`, `DATABASE_URL`, `TICKETING=servicenow|jira`, and the model key only once AI triage is approved by security.

### 10.4 Deployment profiles
- **On-prem (recommended first):** Docker Compose or a Kubernetes namespace on the management network; 2 backend replicas; site Postgres; TLS at the reverse proxy.
- **AWS:** `deploy/terraform/` (ECS Fargate, RDS, ECR, CloudFront), GitHub Actions deploy via OIDC; see `deploy/deployment-brief.md` and `deploy/runbook-release.md`.
Same container image either way, built once in CI from a tag.

### 10.5 Phased rollout with exit criteria
| Phase | Runs | Exit criterion |
|---|---|---|
| P1 Replay | Detector on recorded Prometheus data incl. one known thermal event | Known event → exactly one zone incident; thresholds tuned and recorded |
| P2 Shadow | Live telemetry; incidents created; no tickets, no pages | 2 weeks; weekly sample reviewed; precision target agreed in writing met |
| P3 One zone | Tickets on for one zone; runbooks notify-only | 4 weeks; ticket noise acceptable; approvals audited; nothing missed that an operator caught first |
| P4 Full hall | All zones; runbook steps call integrations; AI triage optional | Monthly review; forecast compared with facilities' numbers |
| P5 Steady state | Weekly fresh-trace sampling; quarterly threshold review; restore drill every 6 months | `restore.sh` returns a known incident |

Rollback at any phase: `TICKETING=none`, runbooks off, console read-only. Nothing in the hall changes, because nothing was ever actuated.

### 10.6 Go-live checklist (P4)
T16 live and one restore drill passed · detector server-side · RBAC verified with a test user · ticketing verified against the site instance · CRAC telemetry wired or deferred with the lower confidence documented · thresholds tuned on replay data · runbook steps mapped to real notifications, no actuation · security review signed · owner named · specs updated for every decision.

## 13. Tools

| Tool | Role in the project | Where |
|---|---|---|
| **Claude** (agentic coding harness) | The contractor. Drafted the specs from my intent, wrote the console and backend, built the evals and deploy scaffold, and reported spec-versus-code conflicts instead of patching around them. Two parallel builder agents worked at the same time: one on the AI triage feature, tests and evals; one on Terraform, workflows and backup/restore. | Whole repo; `CLAUDE.md` is what it reads every session |
| **Anthropic API** | The runtime model inside the product: one bounded call per triage note that returns a structured draft. Independent of the harness above; a coding agent can build a product with no runtime AI at all. | `backend/ai/triage.py`, `specs_with_AI_feature/AI-spec.md` |
| **FastAPI** | The backend: WebSocket telemetry feed, incident API, OIDC auth, ticket sync, triage endpoint. | `backend/app.py` |
| **Chart.js** | Time-series charts in the console: rack inlet/CPU, site load/PUE, capacity forecast. | `frontend/index.html` |
| **pytest** | 73 tests: API contract, AI-1…AI-8, OBS-1…OBS-3, the no-write-path guard. | `backend/tests/` |
| **ruff** | Linter; first step of the definition of done. | `scripts/verify.sh`, `ruff.toml` |
| **OpenTelemetry + Arize Phoenix** | Observability: one trace per model call with named spans; Phoenix is the local UI for reading traces and adding human labels during evaluation. | `backend/ai/tracing.py`, `specs_with_AI_Evals/observability-spec.md`, `observability-runbook.md` |
| **Terraform** | AWS infrastructure as code; remote state in S3 + DynamoDB; snapshot before destroy. | `deploy/terraform/` |
| **GitHub Actions** | CI on every push (lint, tests, mocked evals); deploy on `main` via OIDC → ECR → migration task → ECS → smoke test; manual trigger for recovery. | `.github/workflows/` |
| **AWS** (ECS Fargate, RDS, ECR, CloudFront) | Fargate runs the backend container, RDS PostgreSQL holds incidents, ECR stores images, CloudFront provides HTTPS in front of the load balancer. Scaffolded, not yet applied. | `deploy/terraform/main.tf`, `deploy/deployment-brief.md` |
| **Cloudflare Quick Tunnels** | Temporary public URL for the local app, for a demo without a cloud account. | `deploy/scripts/demo-tunnel.sh` |

Claude in the first row is AI *in development*; the Anthropic API in the second row is AI *in the product*. The course treats those as independent choices, and the ADRs record why each was made.

## License

MIT.
