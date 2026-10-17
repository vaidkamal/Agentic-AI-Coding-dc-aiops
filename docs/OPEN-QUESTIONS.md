# OPEN-QUESTIONS.md — contradictions found while implementing phases 8–9

Each item: what the documents say, what was built (the most conservative reading), and what the
architect needs to decide. Nothing under `specs*/` or `evals/golden/` was edited.

## Q1. Base path of the existing endpoints
- api-contract-spec says base path `/api/v1`; the restored `backend/app.py` and `frontend/index.html`
  use `/api/incidents` (no `/v1`), while the new triage route is `/api/v1/ai/triage` in both.
- Built: existing routes left exactly as they were (brief: "keep existing endpoints unchanged");
  triage at `/api/v1/ai/triage`. Contract tests target `/api/incidents`.
- Decide: move the incident routes to `/api/v1/...` (and update the frontend), or amend the
  contract to document the current paths.

## Q2. `kind: "other"` versus the list invariant
- AI-spec §4 row 8 and golden case T6 require `kind: "other"` together with
  `clarification_fields: ["kind"]`. api-contract-spec Rev 2 says the union of the two lists
  "equals the null fields among kind, key, sev" — `"other"` is not null, so the two cannot both hold.
- Built: `"other"` counts as unresolved for `kind` (it means "not catalogued", not a decision), so
  the invariant reads: union = null fields among kind/key/sev ∪ {kind if kind == "other"}.
  Everything else in the invariant is enforced strictly (disjoint, no field outside kind/key/sev).
- Decide: confirm this reading in the contract, or change row 8 / T6 to `kind: null`.

## Q3. Where month-to-date spend is persisted
- backend-spec Rev 2 §10: "Persist month-to-date spend in the database." The backend has no
  database today (`/healthz` reports `db: memory`; records live in a dict).
- Built: `backend/ai/budget.py` keeps spend in memory and persists it to a SQLite file when
  `AI_BUDGET_DB` is set (env, as the brief directed). Unset = in-memory, lost on restart.
- Decide: wire `AI_BUDGET_DB` in docker-compose/.env.example now, or defer until the
  `DATABASE_URL` store from backend-spec §2 exists and move the table there.

## Q4. `incident.save` span needs data the write contract does not carry
- observability-spec §1 wants `incident.save` with `draft_request_id` and
  `fields_changed_by_operator`; api-contract Rev 2 says `POST /incidents` is unchanged.
- Built: the span is emitted on every `POST /api/incidents` with `incident_id`; the two linking
  attributes come from optional request headers `X-Draft-Request-Id` and
  `X-Draft-Fields-Changed` (comma list). The JSON body is unchanged. The frontend does not send
  these headers yet (frontend work was outside this brief), so live traces will show them as null.
- Decide: approve the headers and add them to the frontend confirm call, or drop the two
  attributes from the spec.

## Q5. "Six spans" in OBS-1
- observability-spec §1 lists six spans but `incident.save` is "a separate trace" that only
  exists when the operator confirms. A triage call produces five spans in one trace.
- Built/tested: `test_spans_*` asserts the five spans share one trace on a triage call and
  that `incident.save` is a root span of its own on the write path.

## Q6. Creating `scripts/verify.sh` against the repository rules
- CLAUDE.md and `.claude/settings.json` forbid editing `scripts/verify.sh`; the brief asked for
  it to be written and the file did not exist.
- Built: created as specified. Please review it once and then treat it as frozen.
- Note: ruff flags the pre-existing phase-1 modules for one-statement-per-line style and
  exception chaining; `ruff.toml` exempts those files rather than rewriting reviewed code.

## Q7. Rack numbers outside the hall
- The hall has racks `A-01`…`D-06`. The spec asks for a zone letter check; it says nothing about
  the rack number. `normalise_key` accepts `Z-NN` with NN 1–99 and rejects zones outside A–D.
- Decide: should `B-12` be rejected as unusable output (503) or passed through for the operator
  to correct? Currently passed through (conservative: never hide what the model said).

## Q8. Saving a draft with `kind: "other"`
- backend-spec §4 restricts saved `kind` to four values and the contract says 422 otherwise,
  but the restored `app.py` `Incident` model does not enforce enums (pre-existing gap, phase 1).
  A draft with `kind: "other"` would therefore be accepted by `POST /api/incidents` today.
- Not changed (existing endpoints frozen). Decide whether to tighten the model now.

## Q9. Dependency pins
- Pre-existing pins (fastapi 0.115.0, pydantic 2.9.2, httpx 0.27.2, …) were kept. New packages
  were pinned to the versions that installed cleanly alongside them on 2026-10-17:
  anthropic 1.15.0, opentelemetry-* 1.45.1, pytest 9.1.1, pytest-asyncio 1.4.0.

## Q10. Spec paths in CLAUDE.md
- CLAUDE.md points at `specs/AI-spec.md`, `specs/observability-spec.md` and
  `specs/observability-runbook.md`; those files live under `specs_with_AI_Evals/`.

## Q11. Mocked review table and baseline
- The runbook's review table (§C–D) and baseline (§9.6) are meant to come from a live run with
  Phoenix. Budget approval for live calls was not available in this session, so
  `evals/review-table.md` and `evals/baseline.md` are explicitly labelled as produced from the
  mocked run; Phoenix note and `human_*` columns are marked not available.

---
# Architect decisions — 2026-10-17 (each decision names the documents it changes)
| Q | Decision | Documents updated |
|---|---|---|
| Q1 | Code follows the contract. Incident routes move to `/api/v1/incidents`; `/api/incidents` kept as an alias for one release and listed as deprecated. Console calls `/api/v1`. | api-contract-spec §3 (both revisions), frontend |
| Q2 | Confirm the builder's reading: `kind: "other"` is "not catalogued", therefore unresolved. Invariant: union = null fields among kind/key/sev ∪ {kind if "other"}. | api-contract-spec Rev 2 §7, AI-spec §5 |
| Q3 | `AI_BUDGET_DB` wired in compose and `.env.example` now; moves to the `DATABASE_URL` store with T16. | backend-spec Rev 2 §10, .env.example |
| Q4 | Approve the two headers; console sends `X-Draft-Request-Id` and `X-Draft-Fields-Changed` on confirm. | observability-spec §1, frontend |
| Q5 | Wording fixed: five spans per triage trace plus a separate `incident.save` trace linked by `request_id`. | observability-spec §1, OBS-1 |
| Q6 | `scripts/verify.sh` reviewed and frozen. | — |
| Q7 | Pass through; the operator corrects. Hall size is not a model concern. Recorded in AI-spec §4. | AI-spec §4 |
| Q8 | Tighten now: `Incident.kind`/`sev`/`runbook` become enums → 422. `kind: "other"` cannot be saved; the console disables Confirm when kind is `other`. | backend-spec §4 (already says so), frontend |
| Q10 | CLAUDE.md paths corrected to `specs_with_AI_Evals/`. | CLAUDE.md |
| Q11 | Accepted: mocked baseline labelled as such; live baseline is phase 9.6b, pending budget approval. | ai-implementation-plan |
| Persistence (deploy builder) | Phase 7 proof is blocked until T16 (DB). Ticket system is the record meanwhile. | implementation-plan §Phase 7 |
