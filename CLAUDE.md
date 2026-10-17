# DC-North AIOps — project instructions

Read specs/goal-spec.md for scope and success.
Read specs/frontend-spec.md for screens and flows.
Read specs/backend-spec.md for data and rules.
Read specs/api-contract-spec.md for shared messages.
Read specs_with_AI_Evals/AI-spec.md for the AI triage feature (model proposes; the application saves).
Read specs_with_AI_Evals/observability-spec.md and observability-runbook.md before touching tracing or evals.

Report conflicts and open decisions before implementation. If the documents disagree, bring the conflict back to me.

## Stack
Frontend: single self-contained HTML (no build step), Chart.js 4.4.1.
Backend: Python 3.12, FastAPI, httpx, python-jose, anthropic SDK, OpenTelemetry → Phoenix.
Database: PostgreSQL (SQLite for local dev). Tests: pytest. CI: GitHub Actions.

## Run / Test / Verify
Run:    docker compose up --build        (console at http://localhost:8080)
Test:   cd backend && pytest -q
Verify: ./scripts/verify.sh              ← definition of done. Fix and re-run until green.

## Rules
- Spec before code. No task that is not in specs/implementation-plan.md.
- Fix the spec first when verification fails; never patch code around an ambiguous spec.
- Runbooks require explicit operator approval. Never auto-execute.
- The model proposes incident drafts; only POST /api/incidents after operator confirmation writes.
- Provider keys, ticketing credentials and OIDC settings come from env only.
- Keep each phase number when requesting work and recording results.
- Do not edit specs/, scripts/verify.sh or .claude/settings.json without asking (see settings).
