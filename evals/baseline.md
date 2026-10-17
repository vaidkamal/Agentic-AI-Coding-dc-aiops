# baseline.md — AI triage evaluation baseline

## Mocked baseline (2026-10-17)

Command: `python evals/run_cases.py --mock` (results: `evals/results/20261017T161134Z.json`)
Model: `mock` (fake client, canned outputs from `evals/mock_outputs.json`)
Prompt version: v1 · Rules version: v1 · Grader version: v1 · Tracing: off

What this establishes: the deterministic checks, the post-validation code path (rack-id
normalisation, list invariants), the budget reserve/settle wrapper and the report format all
work end to end. What it does not establish: anything about the real model's behaviour; the
fixtures were written to satisfy the expectations.

| Family | Cases | pass | fail | unable_to_assess | not_applicable | budget_blocked |
|---|---|---|---|---|---|---|
| zone-thermal | 1 | 1 | 0 | 0 | 0 | 0 |
| rack-cpu | 1 | 1 | 0 | 0 | 0 | 0 |
| normalisation | 1 | 1 | 0 | 0 | 0 | 0 |
| clarification | 1 | 1 | 0 | 0 | 0 | 0 |
| correction | 1 | 1 | 0 | 0 | 0 | 0 |
| out-of-catalogue | 1 | 1 | 0 | 0 | 0 | 0 |
| boundary | 2 | 2 | 0 | 0 | 0 | 0 |
| **total** | **8** | **8** | **0** | **0** | **0** | **0** |

Failures / assessed cases: 0 / 8. Unassessed: 0.
Nominal cost: $0.0144 (fake usage of 900 in / 180 out tokens per call at the default price
table $1 / $5 per million; no money was spent).


## Endpoint run through Phoenix (2026-10-17, fake model)

Command: backend started with `TriageService(client=FakeAnthropic(...))` injected and
`PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces`; T1–T8 sent over HTTP to
`POST /api/v1/ai/triage`; T1 confirmed via `POST /api/v1/incidents` with
`X-Draft-Request-Id` / `X-Draft-Fields-Changed: probable_cause`.
Results: `evals/results/endpoint-run-mockmodel-20261017.json` (responses),
`evals/results/phoenix-traces-mockmodel-20261017.json` (exported spans),
`evals/results/phoenix-traces-20261017.png`, `phoenix-trace-detail-20261017.png` (UI).

What this establishes (OBS-1…3 against a running Phoenix, not only the in-memory exporter):
- 8 traces, each with `http POST /api/v1/ai/triage` → `budget.reserve` → `anthropic.triage`
  (→ `triage.validate`) → `budget.settle`, carrying `request_id`, `model`, `prompt_version`,
  `rules_version`, sanitised input, output draft and token usage.
- One `incident.save` span with `incident_id=INC-501`, `draft_request_id` = T1's request id,
  `fields_changed_by_operator=["probable_cause"]`.
- No API key or bearer token in any exported attribute.
- 16 earlier traces carry `error: TypeError …` from a mis-constructed fake client in the
  launcher; the endpoint returned 503 "model unavailable" as the spec requires, and the error
  attribute in the trace is how the fault was found. They are left in the export deliberately.

| Case | HTTP | kind | key | sev | runbook | missing | clarification | verdict vs expectation |
|---|---|---|---|---|---|---|---|---|
| T1 | 200 | thermal-zone | C | crit | rb-crac | [] | [] | pass |
| T2 | 200 | cpu | B-04 | warn | rb-cpu | [] | [] | pass |
| T3 | 200 | psu | D-02 (from "D-2") | crit | rb-psu | [] | [] | pass |
| T4 | 200 | null | A | null | null | [kind, sev] | [] | pass |
| T5 | 200 | cpu | B-05 | warn | rb-cpu | [] | [] | pass |
| T6 | 200 | other | null | null | null | [key, sev] | [kind] | pass |
| T7 | 200 | thermal-rack | A-01 | null | rb-airflow | [sev] | [] | pass |
| T8 | 200 | other | B-02 | null | null | [sev] | [kind] | pass |

Still a fake model: these verdicts say the pipeline, contract and tracing work; they say
nothing about the real model. The live baseline below remains pending.

## Live baseline

Pending. Run `python evals/run_cases.py --live` after approving the printed estimate
(8 calls, upper bound ≈ $0.05 at the default price table against `AI_MONTHLY_BUDGET_USD`).
Record the same table here with the model name, `request_id`s and the real cost, then fill
`evals/review-table.md` from the Phoenix traces and run the judge on the two boundary cases.
