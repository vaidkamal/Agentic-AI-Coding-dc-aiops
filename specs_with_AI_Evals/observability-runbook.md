# observability-runbook.md — reviewing AI triage traces

<!-- Weekend 5. Analyze → Measure → Improve. Preserve the originals; review exported content before sharing it with another service. -->

## A. Start Phoenix locally
```
pip install arize-phoenix
phoenix serve            # UI at http://localhost:6006
export PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces
docker compose up --build
```
Confirm `/healthz` reports `"tracing": "on"`.

## B. Produce the review material (T1–T8)
```
python evals/run_cases.py --cases evals/golden/cases.json --live     # one live call per case, asks for budget approval
```
Each run prints the `request_id` per case; Phoenix shows one trace per case under project `dc-aiops-local`.

## C. Open coding (one note per observation)
For each trace: open the `anthropic.triage` span → compare `output.draft` with the case's expectation → add a Note: expected behaviour, observation, provisional code. Keep the trace link. Label the four `human_*_v1` fields.

## D. Export the review table
Suggested prompt to the coding harness:
> Read specs_with_AI_Evals/observability-spec.md and this runbook. Export only the selected T1–T8 traces, their Phoenix notes and `human_*` annotations. Join them by trace and span id into a review table (evals/review-table.md). Keep one row per observation, with request context, evidence, original note, provisional code and reviewer. Mark missing fields explicitly. Show me the table before grouping it.

## E. Axial coding → codebook
Suggested prompt:
> Using only the reviewed table, propose a small set of failure categories. For each give a definition, inclusion and exclusion rules, supporting case ids, a clear failure, a non-failure and a borderline example. Preserve successes and uncertain observations. Allow multiple labels per case. Show the mapping from every original note to a category and flag unsupported groupings for my review.
The architect approves each rule and records its version in evals/codebook.md before any check is automated.

## F. Turn findings into checks
> Read the approved codebook and the selected cases. Map each criterion to a deterministic check, integration test or semantic rubric. Show what each check establishes and what remains unknown. Add tests using independent expectations and frozen evidence. Include failure, non-failure and unavailable-evidence cases. Report results by criterion.
Verdict vocabulary: pass / fail / unable_to_assess / not_applicable / budget_blocked. Report failures ÷ assessed cases; list unassessed separately.

## G. When checks run
| Trigger | What runs |
|---|---|
| Every push (CI) | `pytest` with mocked model: shape, normalisation, bounds, budget, injection, no-write path. No paid calls. |
| Before accepting a prompt/model change | `python evals/run_cases.py --live` on the golden set; compare by case family; judge only on request. |
| Pre-release | Live run against staging; review changed verdicts, cost and unassessed cases. |
| Ongoing | Sample fresh traces weekly; new failure kinds become golden cases. |

## H. Hill-climbing (only after cases and grader are approved)
> Focus on <one failure category>. Propose edits only to the triage system prompt's rules section. Keep the grader, model and write permissions fixed. Show each patch, changed verdicts, cost and regressions. Reserve untouched cases for a final check. Ask me to approve the run budget before paid calls.
One edit per round. Keep if the target category improves and no other family regresses; otherwise revert.

## I. Reading a failure
- "Said zone when it was one rack" → scope rule; check `rules_version`.
- Draft valid but `sev` invented for a 25 °C reading → boundary rule, not schema.
- 503 with `unusable model output` → look at `triage.validate.rejection_reason` before touching the prompt.
- Budget blocked → `budget.reserve.allowed=false`; raise `AI_MONTHLY_BUDGET_USD` consciously, do not bypass.
