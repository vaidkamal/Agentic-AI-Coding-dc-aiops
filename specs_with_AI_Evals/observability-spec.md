# observability-spec.md — AI triage tracing

<!-- Weekend 5. "The application must send these records through its SDKs or tracing instrumentation." Capture gaps must remain visible. -->

## 1. What we record
For every call to `POST /ai/triage`, one **trace** with the first five **spans** below; the operator's confirmation produces a separate `incident.save` trace linked by `request_id`:
| Span | Attributes |
|---|---|
| `http POST /api/v1/ai/triage` | `request_id`, `user.sub_hash` (sha256, first 12), `hall`, `history_len`, `input.chars`, HTTP status, latency ms |
| `budget.reserve` | `reserved_usd`, `mtd_usd_before`, `allowed` |
| `anthropic.triage` | `model`, `max_tokens`, `timeout_s`, `input.text` (sanitised: emails/phones masked), `input.draft` (JSON), `output.draft` (JSON), `output.missing_fields`, `output.clarification_fields`, `output.reply`, `usage.input_tokens`, `usage.output_tokens`, `stop_reason`, `prompt_version`, `rules_version` |
| `triage.validate` | `normalised_key_from`, `normalised_key_to`, `valid` (bool), `rejection_reason` |
| `budget.settle` | `actual_usd`, `mtd_usd_after` |
| `incident.save` (separate trace) | `incident_id`, `draft_request_id` (header `X-Draft-Request-Id`), `fields_changed_by_operator` (header `X-Draft-Fields-Changed`, comma list) |

## 2. Where it goes
OpenTelemetry OTLP/HTTP → **Phoenix** (Arize), local at `http://localhost:6006`, project `dc-aiops-local`. `PHOENIX_COLLECTOR_ENDPOINT` env; when unset, tracing is a no-op and `/healthz` reports `tracing: off` so the gap is visible.

## 3. What we never record
The provider API key; raw bearer tokens; operator names in plain text (hash only); ticket credentials.

## 4. Versions carried on every span
`app.version` (git sha), `prompt_version`, `rules_version` (AI-spec §4 table version), `model`, `grader.version` when an eval run is the caller.

## 5. Human annotation fields (Phoenix)
| Field | Type | Values |
|---|---|---|
| `human_extraction_v1` | categorical | pass, fail, unable_to_assess |
| `human_scope_v1` (zone vs rack correctly chosen) | categorical | pass, fail, unable_to_assess |
| `human_boundary_v1` (no invented severity; injection treated as data) | categorical | pass, fail, unable_to_assess |
| `human_clarity_v1` (reply asks the right question) | categorical | pass, fail, unable_to_assess |
| `human_note` | free text | one observation per note; keep the trace link |
Use a separate note for each observation. "Bad answer" is too broad to investigate.

## 6. Acceptance criteria
| ID | Criterion | Command |
|---|---|---|
| OBS-1 | Every triage call produces one trace with the five triage spans; a confirm produces an `incident.save` trace | `pytest tests/test_tracing.py -k spans` (in-memory exporter) |
| OBS-2 | API key and bearer never appear in any span attribute | `pytest -k redaction` |
| OBS-3 | `/healthz` shows `tracing: off` when the collector is unset | `pytest -k healthz_tracing` |
