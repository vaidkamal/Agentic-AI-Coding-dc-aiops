# implementation-plan.md — DC-North AIOps

<!-- Weekend 3, Lecture 6 (Table 5.1 style). Strategy: local-first, cloud-last. Keep phase numbers when requesting work and recording results. Date updates; keep outstanding work visible. -->

| Phase | Work | Completion evidence | Status (2026-10-17) |
|---|---|---|---|
| 0 | Environment and repository | Required tools work; project structure committed. | Done |
| 1 | Backend core | API matches api-contract-spec; `pytest` green; `/healthz` 200. | Done |
| 2 | Frontend core | Main journey (inject → incident → approve → resolve) completes; data visible after reload. | Done |
| 3 | Local hardening | Three fault injections clean; 360 px and both themes checked; feed-loss fallback observed. | Done |
| 4 | Cloud infrastructure | Terraform apply drift-free: VPC, ALB, ECS, RDS, ECR, OIDC deploy role. Config tracked in Git. | Scaffold written; apply pending account |
| 5 | Backend release | CI lint+test → image pushed → migration task exit 0 → service stable → `/healthz` 200 on ALB. | Workflow written; run pending |
| 6 | Hosted frontend | Console served over HTTPS (CloudFront); creates and resolves an incident against the hosted API. | Pending |
| 7 | Backup and restoration | Same `INC-nnn` with original `opened` retrieved after snapshot → destroy → rebuild. | Scripts written; proof **blocked** until T16 (incidents persisted to RDS) |
| 8 | AI triage feature (AI-spec.md) | Free-text note → structured draft → operator review → saved incident; 20 s / 1,024-token bounds enforced; 71+ tests green. | Done locally; see specs_with_AI_feature |
| 9 | Observability and evals | Phoenix traces for every model call; golden set T1–T8; deterministic checks + judge; baseline recorded. | Done locally; see specs_with_AI_Evals |

Review before each phase: which reviewed requirement does this implement? what must already exist? what will we observe, and what remains unverified?

Superseded notes: phase 7 was added when "incidents must survive teardown" became a requirement (2026-10-17). Phases 8–9 were added with the AI feature; they do not change phases 4–7.
