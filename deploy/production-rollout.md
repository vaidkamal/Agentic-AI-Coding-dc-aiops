# Production rollout guide — from POC to a live data-centre hall

<!-- Weekend 4 §6.10 "deployment and recovery brief", extended for a real site. Decisions here must be carried back into backend-spec, api-contract-spec and the implementation plan when adopted. -->

## 0. Honest readiness assessment

| Area | POC today | Required for production | Gap |
|---|---|---|---|
| Telemetry | Simulator, or Prometheus with sample PromQL | Real exporters per rack/zone with `rack`,`zone` labels; CRAC telemetry | Exporter mapping per site; CRAC series (item 4 in README §8) |
| Detection | Runs in each operator's browser | One authoritative detector per hall so all operators see the same incidents | Move detector to a backend worker (ADR-01 revisit condition) |
| Incident store | In-memory dict | PostgreSQL with backups | T16 |
| Runbooks | Steps simulated in the console (1.4 s cadence) | Steps that page people / call tools, with real completion signals | Runbook executor in backend with integrations (PagerDuty/Opsgenie, ServiceNow task, email) |
| Auth | OIDC validation; any operator may approve | Role separation: operator / shift-lead (approve) / read-only | RBAC check on approve; `roles` claim already parsed |
| Ticketing | ServiceNow / Jira sync, tested with mocks | Verified against the site's instance and assignment groups | Integration test against a sandbox instance |
| AI triage | Single bounded call; rate limit per process | Replica-wide rate limit; provider egress approved by security | Shared limiter (Redis); or disable the feature on day 1 |
| Hosting | AWS scaffold (Terraform) | Most sites run ops tooling **inside** the DC network; cloud is optional | On-prem Docker/Kubernetes profile (below) |
| HA | Single container | Two backend replicas behind a load balancer; DB with failover | Compose → Kubernetes/ECS with 2 replicas; RDS Multi-AZ or on-prem Postgres HA |
| Change control | None | Change ticket, maintenance window, rollback plan | §6 of this guide |

Rule for the whole rollout: **the system observes and advises before it is allowed to page anyone, and it never actuates equipment.** That matches ADR-03 and the course's blast-radius principle.

## 1. What the data centre must provide

### 1.1 Telemetry sources (one of each, labelled by rack and zone)
| Signal | Typical source | Exporter | Metric expected by the adapter |
|---|---|---|---|
| Inlet temperature per rack | Environmental sensors (e.g. rack-front probes via BMS/DCIM, SNMP or Modbus) | `snmp_exporter` / vendor exporter / DCIM API bridge | `dc_rack_inlet_celsius{rack,zone}` |
| CPU per host | Host agents | `node_exporter` | `node_cpu_seconds_total{rack,zone}` |
| Power per rack | Intelligent PDUs (SNMP) | `snmp_exporter` with the PDU MIB | `pdu_outlet_power_watts{rack,zone}` |
| Host up/down | Prometheus scrape result | — | `up{rack,zone}` |
| Facility power (for PUE) | Main switchboard meter / BMS | Modbus or BMS exporter | `facility_power_kw` |
| CRAC state (recommended) | CRAC controller / BMS | BMS exporter | `crac_supply_celsius{zone}`, `crac_compressor_state{zone}` |

Labels are the contract. Add them with Prometheus relabeling or `file_sd` (see `prometheus.yml`); racks must be `Z-NN`, zones single letters, and the zone↔CRAC mapping must match `AI-spec.md §4` and the console's `crac` table.

### 1.2 Network and placement
- Backend and Prometheus on the **management network**, not the production data network.
- Backend needs: inbound HTTPS from operator workstations; outbound to Prometheus, the IdP (JWKS), ticketing, and (only if AI triage is enabled) the model provider through the corporate egress proxy.
- No path from the backend to BMS/PDU write interfaces. Verify with a firewall rule review; this is the technical guarantee behind "never actuates".

### 1.3 Identity and ticketing
- OIDC application in the site IdP (Entra ID / Okta / Keycloak) with a `roles` claim: `dc-operator`, `dc-shift-lead`, `dc-readonly`.
- Ticketing service account with rights to create incidents and add work notes in the DC Operations assignment group / project.

### 1.4 People
- Named **owner** (shift lead) who approves runbooks and reviews the weekly incident sample.
- Facilities contact for CRAC/PDU questions during the pilot.

## 2. Configuration

All configuration is environment, never code. Full key list in `.env.example`; production values live in the secret manager (AWS Secrets Manager, Vault, or Kubernetes Secrets).

| Key | Production value |
|---|---|
| `ENV` | `production` (refuses `AUTH_MODE=dev`) |
| `TELEMETRY_ADAPTER` | `prometheus` |
| `PROM_URL`, `PROM_Q_INLET`, `PROM_Q_CPU`, `PROM_Q_POWER`, `PROM_Q_UP`, `PROM_Q_FACILITY` | Site-specific PromQL (validate each in the Prometheus UI first) |
| `POLL_SECONDS` | 2–10 (match sensor scrape interval; 2 s is the console design point) |
| `AUTH_MODE`, `OIDC_ISSUER`, `OIDC_AUDIENCE` | `oidc`, IdP issuer URL, app client id |
| `DATABASE_URL` | PostgreSQL DSN (after T16) |
| `TICKETING`, `SNOW_*` / `JIRA_*` | Site instance, service account from secret manager |
| `ANTHROPIC_API_KEY`, `AI_MODEL`, `AI_MONTHLY_BUDGET_USD` | Only when AI triage is approved; otherwise leave the key unset and the Triage tab offers manual entry only |
| `PHOENIX_COLLECTOR_ENDPOINT` | Internal collector, or unset (`/healthz` shows `tracing: off`) |

Hall layout (zones, racks per zone, zone↔CRAC, design kW, 80 % planning line) is currently constant in the console; make it a `hall.json` served by the backend before a second hall is added.

## 3. Deployment profiles

### Profile A — on-premises (recommended for a first site)
Docker Compose on a management VM, or a Kubernetes namespace if the site already runs one.
```
backend      2 replicas, image from the site registry, read-only root FS, non-root user
prometheus   existing site instance, or the bundled one scraping the exporters
postgres     site DB cluster, or a managed instance; nightly dump + PITR
reverse proxy  TLS termination (nginx/Traefik) with the site certificate
```
Deploy: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` from a tagged release; config from `.env` rendered by the secret manager.

### Profile B — AWS (Terraform in `deploy/terraform/`)
ECS Fargate + RDS + CloudFront, GitHub Actions deploy via OIDC. Appropriate when the site already uses AWS for ops tooling and the management network is reachable (VPN/Direct Connect to Prometheus). Steps in `deploy/deployment-brief.md` and `deploy/runbook-release.md`.

Either way the release artefact is the same container image, built once in CI from a tag.

## 4. Phased rollout (each phase has an exit criterion; keep the phase numbers in change tickets)

| Phase | What runs | Who sees it | Exit criterion |
|---|---|---|---|
| P1 Replay | Backend + detector against **recorded** Prometheus data from a past month, including at least one known thermal event | Project team | Known event produces exactly one zone incident with the right timing; false-positive rate over the month reviewed and thresholds (window, σ, ceilings) tuned, recorded in `research` notes |
| P2 Shadow | Live telemetry, incidents created, **no tickets, no pages**; runbooks disabled | Shift leads, read-only | Two weeks; every incident reviewed in the weekly sample; precision acceptable to the owner (target agreed in writing, e.g. ≥ 80 % of incidents judged actionable) |
| P3 One zone | Ticket sync on for one zone; runbooks enabled with steps that only notify (no tool calls) | Operators on shift | Four weeks; ticket noise acceptable; approvals and timelines audited; no incident missed that an operator caught first |
| P4 Full hall | All zones; runbook steps may call integrations (page, create task); AI triage optionally enabled | All operators | Monthly review; capacity forecast compared with the facilities team's own numbers |
| P5 Steady state | Weekly fresh-trace sampling (Weekend 5 habit), quarterly threshold review, restore drill every six months | Owner | Drill passes: `restore.sh` returns a known incident |

Rollback at any phase: set `TICKETING=none`, disable runbooks, keep the console read-only. Nothing in the DC changes because the system never changed anything.

## 5. Validation before each phase

- `./scripts/verify.sh` green on the tagged commit.
- Prometheus queries return non-empty results for every rack (`count by (zone)(dc_rack_inlet_celsius) == 6` per zone).
- `/healthz` reports `ok`, `adapter: prometheus`, `db: ok`, `tracing` as intended.
- Browser check from an operator workstation through the real proxy and IdP (the course's "a terminal request can succeed while the browser blocks the response").
- Fault injection is **not** used on live equipment; use replay data or a sensor in a test rack.

## 6. Change control, security, operations

- Change ticket per phase with rollback plan (above) and the exit criterion as acceptance.
- Security review items: management-network placement, no write path to BMS/PDU, secrets in the secret manager, provider egress (if AI enabled), log retention, OIDC role mapping.
- Backups: Postgres nightly + PITR; restore drill as in Phase 7 of the implementation plan.
- Monitoring the monitor: alert if `/healthz` fails, if the poll loop stalls (> 3 × `POLL_SECONDS`), or if any zone has fewer racks reporting than expected.
- On-call: the console is an aid; the existing NOC procedures remain authoritative until P4 exit.

## 7. Go-live checklist (P4)
- [ ] T16 persistence deployed; restore drill passed once
- [ ] Detector moved server-side; two operators see identical incident lists
- [ ] RBAC: only `dc-shift-lead` can approve; verified with a test user
- [ ] Ticketing verified against the site instance (create, work note, close)
- [ ] CRAC telemetry wired or explicitly deferred with the lower confidence documented
- [ ] Thresholds tuned on replay data; values recorded with dates
- [ ] Runbook steps map to real notification integrations; no actuation anywhere
- [ ] Security review signed; firewall rules reviewed
- [ ] Owner named; weekly review calendar entry exists
- [ ] Specs updated for every decision above (backend-spec §8–9, api-contract snapshot if `crac` added, implementation plan phases 10+)

## 8. What this guide does not promise
No production hall has run this software yet. The POC proves the design and the method; the phases above are how to earn the evidence, one bounded step at a time.
