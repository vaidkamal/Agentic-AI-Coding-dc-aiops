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

## Live baseline

Pending. Run `python evals/run_cases.py --live` after approving the printed estimate
(8 calls, upper bound ≈ $0.05 at the default price table against `AI_MONTHLY_BUDGET_USD`).
Record the same table here with the model name, `request_id`s and the real cost, then fill
`evals/review-table.md` from the Phoenix traces and run the judge on the two boundary cases.
