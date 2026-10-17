# DC-North AIOps

**A spec-driven, agentic-AI-built operations console for a data-centre hall: one correlated incident instead of 24 alarms, a probable cause with confidence, and a runbook the operator approves in one tap. Extended with a bounded AI triage feature (the model proposes; the application saves), evaluated with a golden set, and deployable with backup-and-restore proof.**

Final project for *Agentic AI Coding: From Specification to Deployment* (Prof. Deepak N. Subramani, CDS / QUEST Lab, IISc Bengaluru; CCE Sept–Oct 2026 cohort).

| | |
|---|---|
| Deployed console (Project submission URL) | https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/frontend/ |
| Session transcript | https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/transcripts/dc-aiops_session_log.html |
| Design decision walkthrough and interview preparation | https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/docs/dc-aiops-design-walkthrough.html |
| Architecture (C4, request paths, failure table) | https://vaidkamal.github.io/Agentic-AI-Coding-dc-aiops/dc-aiops-architecture.html |
| Source code | https://github.com/vaidkamal/Agentic-AI-Coding-dc-aiops |

## 1. The problem

Hall 2 has 4 zones, 24 racks, 1,200 kW of design power. Operators watch inlet temperature, CPU, PDU power and host availability on separate screens. When a CRAC unit degrades, all six racks in its zone alarm at once; root cause takes hours because nobody correlates the alarms, and the "fix" is a page to facilities after the damage is done.

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
deploy/                       terraform/ · scripts/ · deployment-brief.md · runbook-release.md
.github/workflows/            ci.yml · deploy.yml
docs/                         design-decisions.md (12 ADRs) · interview-questions.md · OPEN-QUESTIONS.md · test-the-test.md
transcripts/                  session log + link to the raw session
dc-aiops-architecture.html    architecture page (GitHub Pages)
index.html                    GitHub Pages landing page
```

## 5. Run it

```bash
cp .env.example .env            # simulator, dev auth, no ticketing, no AI key needed for the console
docker compose up --build       # http://localhost:8080
./scripts/verify.sh             # ruff · 73 tests · evals --mock · no-write-path grep · CDN hosts → GREEN
```
Try it: Inject fault → "CRAC unit failure (Zone C)" → Incidents tab shows one incident → Approve runbook → watch it resolve. Then open Triage and type a symptom.

AI triage needs `ANTHROPIC_API_KEY`; evals: `python evals/run_cases.py --mock` (free) or `--live` (asks for budget approval first). Observability: `pip install arize-phoenix && phoenix serve`, set `PHOENIX_COLLECTOR_ENDPOINT`.

Deployment: `deploy/deployment-brief.md` (services, permissions, cost drivers, what survives teardown) and `deploy/runbook-release.md`.

## 6. Verification evidence

| Requirement | Check | Result |
|---|---|---|
| Goal-spec success criterion | Inject CRAC failure; walk the journey | One Zone C incident, 91 % confidence, resolved after 5 normal samples |
| API contract | `pytest tests/test_api.py` | 9 passed (201/409/404/409-on-resolved/401, enums → 422, deprecated alias) |
| AI-1…AI-8 | `pytest tests/test_ai_triage.py` (frozen fixtures) | 33 passed; write-path mutation turns it red |
| OBS-1…OBS-3 | `pytest tests/test_tracing.py` | 10 passed |
| Golden set T1–T8 | `python evals/run_cases.py --mock` | 0 failures / 8 assessed (mocked) |
| Test the test | three deliberate faults | each went red, then green on restore |
| Deployment scaffold | `bash -n`, YAML parse, `tofu fmt`, HCL reference check | clean; `terraform validate` and apply pending an AWS account |

## 7. What I learned

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

## 8. What remains

- T16: persist incidents to PostgreSQL → unblocks Phase 7 restore proof.
- Phase 9.6b: live baseline on T1–T8 with Phoenix notes (≈ US$0.06), then open and axial coding on real traces, one hill-climb round on the prompt's rules section, model/effort comparison.
- Phases 4–6: Terraform apply and first deploy on an AWS account (Cloudflare tunnel is the fallback for the demo).
- CRAC supply-temperature series as direct evidence for the zone rule.

## 9. Tools

Claude (agentic coding harness: specs, console, backend, evals, deploy scaffold, with two parallel builder agents for the AI feature and the deployment), Anthropic API for the triage model, FastAPI, Chart.js, pytest, ruff, OpenTelemetry + Arize Phoenix, Terraform, GitHub Actions, AWS (ECS Fargate, RDS, ECR, CloudFront), Cloudflare Quick Tunnels.

## License

MIT.
