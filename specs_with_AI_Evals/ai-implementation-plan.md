# ai-implementation-plan.md — AI triage feature and its evaluation

<!-- Weekend 3 L6 + Weekend 5. Minimal viable agent: a single LLM call with structured output. Add a loop or tools only when evaluation shows the simpler design is inadequate. -->

## Design decision (flowchart from Weekend 6)
- Can explicit rules solve "turn an operator's free-text note into an incident draft"? **No** (wording varies, Hinglish, corrections).
- Does the model need evidence beyond the supplied input? **No** — the note plus the fixed zone/CRAC mapping and runbook catalogue are enough. → **One model call**, structured output, no tools, no loop, no runtime agent.
- Revisit when: evaluation shows ≥ 20 % of real notes need a lookup (e.g. current rack telemetry) to classify. Then compare a bounded single-tool call, not an agent.

## Phases
| Phase | Work | Completion evidence | Status |
|---|---|---|---|
| 8.1 | Schemas + system prompt with rules table v1 | `pytest -k shape` green with mocked model | Done |
| 8.2 | Endpoint with timeout/tokens/no-retry, rate limiter, budget reserve/settle | `pytest -k "bounds or budget"` green | Done |
| 8.3 | Post-validation and rack-id normalisation | `pytest -k normalise` green | Done |
| 8.4 | Frontend Triage tab, draft form, confirm → `POST /incidents` | Manual: T1 note → confirm → incident appears in Incidents tab | Done |
| 8.5 | Draft restoration, stale-reply guard, lost-save message | Manual per frontend-spec §5 additions | Done |
| 9.1 | Tracing per observability-spec; Phoenix locally | `/healthz tracing: on`; one trace per call | Done |
| 9.2 | Golden set T1–T8 with approved expectations | `evals/golden/cases.json` reviewed by architect | Done |
| 9.3 | Live run, open coding, review table | `evals/review-table.md` with ≥ 1 note per case | Done (8 cases, 1 live run) |
| 9.4 | Codebook v1 | `evals/codebook.md` approved | Done |
| 9.5 | Deterministic checks + judge rubric | `python evals/run_cases.py --mock` reports by criterion | Done |
| 9.6 | Mocked baseline recorded | `evals/baseline.md`: pass/fail/unassessed per family | Done |
| 9.6b | Live baseline | same table from `--live`, with cost and Phoenix links | Pending budget approval (est. US$0.06 for 8 calls) |
| 9.7 | Hill-climb one category | Changed verdicts and cost shown; accepted or reverted | Not started |
| 9.8 | Model/effort comparison | Candidates A–D on same cases; lowest-cost config meeting quality chosen | Not started |

## What we can claim today
Eight teaching cases reveal failure kinds; they do not estimate production frequency. The mocked suite protects logic; live evaluation tests behaviour with the real provider and remains to be run against the configured budget.
