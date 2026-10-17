# Design decision records — DC-North AIOps

<!-- Weekend 6: ADR = context, choice, alternatives, consequences, revisit-when. "Keep ownership: explain the request path, authority, failure behaviour and reason for every important choice." -->

## ADR-01 Detection runs in the browser; the backend only feeds, authenticates and persists
- **Context.** 24 racks × 4 metrics at 0.5 Hz; one hall; the reviewer must be able to read the logic.
- **Choice.** Rolling z-score + absolute ceilings in `frontend/index.html`, fed by a fixed snapshot contract.
- **Alternatives.** Stream processor (Flink/Kafka Streams); Prometheus alert rules only.
- **Consequences.** Works with no backend (published demo); logic is one file; two browsers detect independently (acceptable: incidents are deduplicated by id on the server, and the ticketing system is the record).
- **Revisit when.** More than one hall, or when two operators must see exactly the same incident set in real time → move detection to a worker per hall emitting over the same incident API.

## ADR-02 Correlate before alarming: zone pass first, per-rack suppressed
- **Context.** The problem statement is "24 alarms on one screen". The CRAC is the only shared dependency inside a zone.
- **Choice.** ≥ 3 racks in a zone with sustained thermal anomaly → one `thermal-zone` incident; per-rack thermal detection is suppressed while it is open.
- **Alternatives.** One alarm per rack with a grouping view.
- **Consequences.** One actionable incident; the rack list is carried in the evidence line. A genuine second fault in the same zone during the excursion is masked until resolution.
- **Revisit when.** CRAC telemetry (supply temp, compressor state) is available → use it as direct evidence and raise confidence; allow a rack incident to co-exist when its CPU, not inlet, is the anomaly.

## ADR-03 Runbooks are approval-gated; the system never actuates
- **Context.** Blast radius (Weekend 1): shifting cooling or throttling hosts can cause the outage it prevents.
- **Choice.** `startRunbook` is reachable only from the Approve button; runbook steps page people and tools; no endpoint starts a runbook server-side.
- **Alternatives.** Auto-remediate above a confidence threshold.
- **Consequences.** Slower mean-time-to-act by one tap; full audit trail with actor. Principle 2 of CLAUDE.md; AC-3.
- **Revisit when.** ≥ 100 observed approvals of one runbook with zero reversals → consider a per-runbook allowlist with dry-run first.

## ADR-04 Every incident carries a cause, evidence and a confidence number
- **Context.** Operators will not act on a recommendation they cannot interrogate.
- **Choice.** `rca` (plain language), `summary` (evidence), `conf` set per rule from how deterministic its signature is (0.91 zone-thermal, 0.84 rack-CPU, 0.88 PSU, 0.62 single hot rack).
- **Alternatives.** A single "AI says" label; no confidence.
- **Consequences.** Confidence is a rule constant, not a learned probability, and the UI says so in the walkthrough.
- **Revisit when.** Golden traces exist to calibrate confidences against outcomes.

## ADR-05 One telemetry contract; adapters conform, the console never adapts
- **Context.** Exporter metric names differ at every site.
- **Choice.** `Snapshot` schema in api-contract-spec §2; `PROM_Q_*` overrides per site.
- **Alternatives.** Console reads Prometheus directly.
- **Consequences.** Simulator and Prometheus are interchangeable; a malformed snapshot is dropped, never broadcast.

## ADR-06 Feed loss degrades to the simulator, announced
- **Context.** A dead feed must not freeze the UI, but simulated data must never masquerade as real.
- **Choice.** Toast "Feed lost — using simulator", reconnect every 5 s, `/healthz` for the monitoring stack.
- **Consequences.** AC-7. The risk that an operator misses the toast is mitigated by the clock continuing and the reconnect toast.

## ADR-07 The AI feature is one model call with structured output; no runtime agent
- **Context.** Weekend 6 flowchart: rules cannot parse free text (Hinglish, corrections) → test a model. Does it need evidence beyond the input? No: the note, the zone/CRAC map and the runbook catalogue suffice.
- **Choice.** `POST /ai/triage`: single `AsyncAnthropic` call, declared response model, post-validation in code. No tools, no loop.
- **Alternatives.** Agent with a telemetry-lookup tool; rule-based parser; fine-tuning.
- **Consequences.** Cheap (≤ 1,024 output tokens), bounded (20 s), explainable (rules table v1 in the prompt), evaluable (T1–T8).
- **Revisit when.** Evaluation shows ≥ 20 % of real notes need live telemetry to classify → compare one bounded tool call against the baseline on the same cases.

## ADR-08 The model proposes; the application saves
- **Context.** Authority to act (Weekend 6): a suggestion is not permission to change state.
- **Choice.** Triage response carries no incident id and no write; the frontend tracks confirmation; `POST /incidents` is the only write and is called only after operator confirmation. Enforced by test AI-6 (no import path from `backend/ai/` to the incidents router).
- **Consequences.** Injection in operator text cannot cause a write; a stale reply cannot overwrite an operator edit.

## ADR-09 Budget and rate limits are enforced in code, not by token caps
- **Context.** Token caps bound one call, not monthly spend.
- **Choice.** Reserve/settle against `AI_MONTHLY_BUDGET_USD`; 10/min/user process-local limiter; 429 with the reason.
- **Consequences.** The limiter is per replica; documented as such in backend-spec §10.

## ADR-10 Observability through OpenTelemetry to Phoenix, off by default
- **Context.** Weekend 5: evaluation starts from traces; capture gaps must stay visible.
- **Choice.** Six named spans per triage call; no-op when the collector is unset and `/healthz` says `tracing: off`.
- **Consequences.** Local review loop works with one `phoenix serve`; production needs a collector decision (deferred).

## ADR-11 Evaluate with a golden set and deterministic checks first; judge second
- **Context.** "The expert approves the rule; the coding agent implements the checks." A judge must be calibrated against expert labels before it is trusted.
- **Choice.** T1–T8 with architect-approved expectations; mocked checks in CI; live runs on request with budget approval; judge rubric for the two semantic criteria only.
- **Consequences.** CI never pays for model calls; live baseline is a separate, dated artefact.

## ADR-12 Deployment: ECS Fargate + RDS via Terraform, backup before destroy
- **Context.** Course phases 4–7; the restore proof is a known incident retrievable after rebuild.
- **Choice.** Terraform remote state; manual RDS snapshot in `destroy.sh` that aborts the destroy on failure; `restore.sh` greps for the known `INC-nnn`.
- **Alternatives.** Render/Fly.io (cheaper, less control); Kubernetes (more than one hall needs).
- **Consequences.** Monthly cost estimate in deploy/deployment-brief.md; apply is pending an AWS account, recorded as such in the plan.
