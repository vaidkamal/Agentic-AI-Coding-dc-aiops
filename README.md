# DC-North AIOps

Spec-driven data-centre operations console built with an agentic coding harness (IISc "Agentic AI Coding" method).

Start here: `specs/goal-spec.md` → `frontend-spec.md` → `backend-spec.md` → `api-contract-spec.md` → `implementation-plan.md`.
AI feature: `specs_with_AI_feature/AI-spec.md`. Evals and observability: `specs_with_AI_Evals/`.

## Run locally
```
cp .env.example .env
docker compose up --build        # console at http://localhost:8080
./scripts/verify.sh              # definition of done
```

## Deployment (Weekend 4, phases 4–7)

Pipeline: check locally → build packages → prepare the cloud → deploy the version → verify and recover.

| Piece | Where | What it does |
|---|---|---|
| CI | `.github/workflows/ci.yml` | Every push/PR: ruff, `pytest -q`, `evals/run_cases.py --mock`. |
| Release | `.github/workflows/deploy.yml` | Push to `main` or manual run: test → OIDC login → build & push to ECR (git SHA) → register task definition → one-off migration task (exit 0 gate) → update ECS service → stable → `/healthz` on the ALB → smoke create/resolve. |
| Infrastructure | `deploy/terraform/` | VPC, ALB, ECR, ECS Fargate, RDS PostgreSQL (7-day backups, final snapshot), Secrets Manager, GitHub OIDC role, CloudFront. Remote state bootstrap in `backend.tf`. |
| Backup / destroy / restore | `deploy/scripts/backup.sh`, `destroy.sh`, `restore.sh` | Snapshot (must be `available`) → destroy → rebuild from snapshot and prove the same `INC-nnn` with its original `opened` is back (`PASS`). |
| Local demo without AWS | `deploy/scripts/demo-tunnel.sh` | Cloudflare Quick Tunnel to `localhost:8080`, constraints printed. |
| Brief | `deploy/deployment-brief.md` | Services, permissions, cost drivers, checks, what survives teardown, phase status. |
| Runbook | `deploy/runbook-release.md` | Release, reading a failed run, rollback, teardown, restore. |

Status: scaffold written; `terraform apply` pending an AWS account. Open conflicts between the current backend and the deployment contract are listed in the brief, §6.
