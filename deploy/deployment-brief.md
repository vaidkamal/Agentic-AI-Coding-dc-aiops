# Deployment and recovery brief — DC-North AIOps

<!-- Weekend 4: "Check locally → Build packages → Prepare the cloud → Deploy the version → Verify and recover".
     Implements backend-spec.md §8 and implementation-plan.md phases 4–7. Dated 2026-10-17. -->

**Status in one line:** scaffold written and statically validated; nothing has been applied — an AWS account is pending. Until then the course demo runs locally behind a Cloudflare Quick Tunnel (§9).

## 1. Shape of the deployment

```
browser ──HTTPS──▶ CloudFront (TLS, no cache) ──HTTP──▶ ALB :80 ──▶ ECS Fargate task :8080 (uvicorn)
                                                                        │
                                                                        ├──▶ RDS PostgreSQL (private subnet)
                                                                        └──▶ NAT ──▶ IdP JWKS, ServiceNow/Jira, Anthropic
GitHub Actions ──OIDC──▶ IAM deploy role ──▶ ECR push, ECS register/run-task/update-service
```

One region (`ap-south-1`), one VPC, two AZs, one running task. Everything is in `deploy/terraform/`; the pipeline is `.github/workflows/`; operator scripts are `deploy/scripts/`.

## 2. Services, account setup and permissions

| Service | Role in the system | Account setup (manual, once) | Permission boundary |
|---|---|---|---|
| **GitHub Actions** | CI (`ci.yml`) on every push/PR; release (`deploy.yml`) on push to `main` or manual dispatch. | Repository secrets `AWS_DEPLOY_ROLE_ARN`, `ALB_URL`, `SMOKE_TOKEN`; variables `AWS_REGION`, `ECR_REPOSITORY`, `ECS_CLUSTER`, `ECS_SERVICE` (all from `terraform output`). | Workflow has `id-token: write` only; no AWS keys stored. |
| **AWS IAM (OIDC)** | Trusts `token.actions.githubusercontent.com` for `repo:<owner>/dc-aiops:ref:refs/heads/main` only. | `terraform apply` creates the provider and the role (`create_github_oidc_provider=false` if one exists). | ECR push to one repo, ECS register/run/update, `iam:PassRole` on the two task roles, read migration logs. Nothing else. |
| **Amazon ECR** | Image registry; tag = git SHA plus `latest`. | Created by Terraform. | `force_delete = true` so a destroy never stalls on a non-empty repo. |
| **Amazon ECS Fargate** | Runs the API container and the one-off migration task. | Created by Terraform. First revision uses a placeholder image; the first `deploy.yml` run replaces it. | Execution role: pull image, write logs, read one secret. Task role: empty in v1. |
| **ALB** | HTTP entry; health check `/healthz`. | Created by Terraform. | Security group: 80 from anywhere; only the ALB may reach the task port. |
| **CloudFront** | HTTPS for the console without owning a domain; caching disabled. | Created by Terraform. | Public; forwards all headers (Authorization, WebSocket upgrade). |
| **RDS PostgreSQL** | System of record for incidents. | Created by Terraform; master password supplied as `TF_VAR_db_password` from a password manager. | Reachable only from the ECS security group on 5432. Not public. |
| **Secrets Manager** | Holds `DATABASE_URL`; injected into the task at start. | Created by Terraform. | Only the execution role can read it. |
| **S3 + DynamoDB** | Terraform remote state and lock. | **Manual bootstrap**, documented in `deploy/terraform/backend.tf`. | Admin-only; never destroyed by this config. |
| **Cloudflare (Quick Tunnel)** | Course demo alternative, local app → temporary public URL. | None (no account). | None at the edge — see §9. |

Who can do what: the **operator** (course participant) holds admin on the AWS account, the DB password and `gh` auth; **GitHub Actions** holds only the deploy role; the **application** holds nothing AWS-side.

## 3. Cost drivers (labelled estimates)

Rough list prices, `ap-south-1`, October 2026, USD per month at demo traffic. Free tier (first 12 months) is noted but not subtracted. These are **estimates** to show where money goes, not a quote.

| Resource | Driver | Est. USD/month | Note |
|---|---|---|---|
| NAT gateway | 0.045/h + 0.045/GB | **~33** | Largest fixed cost. One gateway, not two (trade-off: AZ outage stops egress). Alternative: tasks in public subnets with public IPs → 0, less tidy. |
| ALB | 0.0225/h + LCU | **~16** | Required for ECS health checks and rolling deploys. |
| RDS db.t4g.micro | 0.016/h | **~12** | Free tier eligible. Single-AZ. |
| RDS storage 20 GB gp3 | 0.115/GB | ~2.5 | Backups free up to 20 GB. |
| Fargate 0.25 vCPU / 0.5 GB × 1 task | 0.0127/h | **~9** | Scales linearly with `desired_count`. Migration task: cents. |
| Secrets Manager | 0.40/secret | ~0.4 | One secret. |
| CloudWatch Logs | 0.50/GB ingested | < 1 | 7-day retention. Container Insights disabled. |
| ECR | 0.10/GB stored | < 1 | Lifecycle policy keeps 10 images. |
| CloudFront | 1 TB free tier | ~0 | Price class 200 (includes India). |
| S3 + DynamoDB (state) | KB-scale | ~0 | |
| **Total while running** | | **≈ 75 / month, ≈ 2.5 / day** | NAT + ALB are 65 %. |
| **Total while destroyed** | snapshots ≤ 20 GB free, state | **≈ 0** | This is why Phase 7 matters: tear down between sessions. |

## 4. Requirements → how each is checked

| Requirement (spec) | Automated check | Manual check |
|---|---|---|
| Lint + tests green before any release (plan 5) | `ci.yml` and the `test` job of `deploy.yml` (`ruff`, `pytest -q`, `evals/run_cases.py --mock`) | Read the job status; do not merge red. |
| Image built in CI, pushed to ECR (spec §8) | `deploy.yml` "Build and push image"; tag `${{ github.sha }}` | `aws ecr describe-images` shows the SHA tag. |
| Migration runs as one-off task before rollout, exit 0 (spec §8) | `deploy.yml` "Run database migration"; rollout stops on non-zero | Read the step's `migrate-result.json` output. |
| Service stable, `/healthz` 200 on ALB (plan 5) | `aws ecs wait services-stable`; curl loop expects `ok: true` | Open `alb_url/healthz` in a browser. |
| Hosted console creates and resolves an incident (plan 6) | Smoke step: `POST /incidents` → 201, `POST /resolve` → 200 `resolved: true` | Open `console_url` over HTTPS, inject a fault, approve, resolve. |
| Console over HTTPS (plan 6) | — | `console_url` is `https://…cloudfront.net`; padlock in browser. |
| Terraform apply drift-free (plan 4) | — | `terraform plan` shows "No changes" after a release (service ignores `task_definition`). |
| OIDC trust limited to repo + branch (plan 4) | — | `aws iam get-role` → `sub` condition. Try a run from another branch: `AssumeRoleWithWebIdentity` is denied. |
| Snapshot before destroy, stop if it fails (spec §8) | `destroy.sh` calls `backup.sh` and exits on non-zero | Observe the snapshot in the RDS console before the plan prints. |
| Same `INC-nnn` with original `opened` after rebuild (plan 7) | `restore.sh … <INC-nnn> <opened>` prints `PASS` | Open the console after restore; the incident timeline shows the original time. |
| Secrets only from env (CLAUDE.md) | — | `grep -r` for keys in the repo; task definition shows `DATABASE_URL` as a secret reference. |
| `AUTH_MODE=dev` refused when `ENV=production` (spec §6) | — (backend test, other agent) | Task env has `ENV=production`, `AUTH_MODE=oidc`. |

## 5. What survives teardown (lifecycle)

`terraform destroy` (via `destroy.sh`) removes every resource in `main.tf`. The table says what is kept, where, and what has to be done on rebuild.

| Thing | Survives destroy? | Where it lives | On rebuild |
|---|---|---|---|
| Incident data (RDS) | **Yes, via snapshot** | Manual snapshot from `backup.sh` (`<db>-manual-<timestamp>`), plus RDS final snapshot. Snapshots are account-level, not in the VPC. | `terraform apply -var snapshot_identifier=…` creates the instance from it. Automated backups (7 days) are deleted with the instance; only snapshots persist. |
| DB master password | **Yes, outside AWS** | Operator's password manager, exported as `TF_VAR_db_password`. | Must be the **same** value: a snapshot keeps the password it was taken with. Terraform does not generate it for exactly this reason. |
| Terraform state | **Yes** | S3 bucket + DynamoDB lock, bootstrapped by hand (`backend.tf`). | `terraform init` finds it; state records the destroyed resources as gone. |
| Container images (ECR) | **No** | `force_delete = true` deletes the repository with its images. | Repository recreated empty; `gh workflow run deploy.yml` rebuilds from source and pushes. `restore.sh` does this. |
| Task definition revisions | **No** (family is recreated at revision 1) | — | First revision uses the placeholder image; the workflow registers the real one. |
| CloudFront hostname | **No** — a new `*.cloudfront.net` name | — | Update anything that embeds it: IdP redirect/allowed origin, bookmarks, the README demo link. The frontend itself uses relative URLs, so no code change. |
| ALB DNS name | **No** | — | Update GitHub secret `ALB_URL` from `terraform output alb_url`. |
| Deploy role ARN | Same name → **same ARN** | IAM (recreated with identical name) | GitHub secret stays valid. |
| `DATABASE_URL` secret | **No** (`recovery_window_in_days = 0`) | — | Recreated from the new RDS endpoint on apply. |
| JWT / OIDC keys | **n/a — nothing to regenerate** | The IdP (Entra ID / Okta / Keycloak) signs tokens; the backend only validates against JWKS. | No key material in the stack. Only the redirect URI (CloudFront hostname) changes. |
| CloudWatch logs | **No** (7-day group is deleted) | — | Export before destroy if a log is evidence. |
| GitHub secrets/variables | **Yes** | GitHub | Refresh `ALB_URL`; the rest are unchanged. |

## 6. Phases 4–7: evidence and current status

| Phase | Work | Evidence of completion | Status (2026-10-17) |
|---|---|---|---|
| 4 Cloud infrastructure | `deploy/terraform/` — VPC (2 public + 2 private subnets, 1 NAT), ALB, ECR, ECS Fargate, RDS (7-day backups, final snapshot), Secrets Manager, GitHub OIDC role, CloudFront. | `terraform apply` completes; a second `terraform plan` shows no changes; `terraform output` lists the values for GitHub. | **Scaffold written.** `terraform fmt`/`validate` could not run (terraform not installed on the authoring machine); apply pending an AWS account. |
| 5 Backend release | `.github/workflows/deploy.yml` | Run page: test green → image pushed (SHA tag) → migration task exit 0 → service stable → `/healthz` `ok:true` on ALB → smoke `201`/`200`. | **Workflow written**, YAML parses. First run pending Phase 4. Migration step is a no-op `python -c "print('no migrations')"` until `backend/alembic.ini` exists (then `alembic upgrade head`, already switched automatically by the step). |
| 6 Hosted frontend | CloudFront in front of ALB, caching disabled. | Console opens on `https://…cloudfront.net`; inject → incident → approve → resolve works against the hosted API. | **Pending** Phase 5. |
| 7 Backup and restoration | `deploy/scripts/backup.sh`, `destroy.sh`, `restore.sh` | `backup.sh` prints an `available` snapshot id; `destroy.sh` refuses without it; `restore.sh … INC-nnn <opened>` prints `PASS`. | **Scripts written**, `bash -n` clean. Proof pending. |

### Open conflicts to resolve before Phase 5 can pass (reported, not patched)

1. **Persistence.** `backend/app.py` keeps incidents in a dict and reports `"db": "memory"`; `requirements.txt` has no SQLAlchemy/psycopg; `.env.example` has no `DATABASE_URL`. backend-spec §2/§8 require PostgreSQL via SQLAlchemy and an Alembic migration. Phase 7's proof is impossible until the backend writes to `DATABASE_URL`. The task definition already injects `DATABASE_URL` and `ENV`.
2. **Base path.** api-contract-spec says `/api/v1`; the code serves `/api/incidents`. `deploy.yml` and `restore.sh` default to `/api/v1`; set GitHub variable / env `API_BASE=/api` as a stop-gap, or align the backend.
3. **Tests and evals.** `cd backend && pytest -q` and `evals/run_cases.py --mock` are what CI runs; `backend/` has no tests directory and `evals/run_cases.py` does not exist yet, so CI is red until the owning agent adds them.
4. **Smoke token.** With `AUTH_MODE=oidc` the smoke step needs a real bearer from the IdP (client-credentials flow or a long-lived test token) stored as `SMOKE_TOKEN`. Decide which.

## 7. Migration step contract

`deploy.yml` runs the same image as a one-off Fargate task with the command overridden, using the service's own subnets and security group so it reaches RDS. It expects `alembic upgrade head` from `/app/backend` (the Dockerfile `WORKDIR`) and gates the rollout on exit code 0. Until `backend/alembic.ini` is added the command is `python -c "print('no migrations')"` — the step detects the file and switches automatically, so the mechanism (run, wait, read exit code, stop on failure) is exercised from the first release.

## 8. Rollback and recovery in one paragraph

Rollback = point the service at the previous task-definition revision (`deploy/runbook-release.md` §4); images are kept for 10 revisions. Recovery after a destroyed environment = `restore.sh` (§5 above). Recovery after a bad migration = restore the pre-release snapshot (`backup.sh` before every schema change is the rule) and roll back the service. Reading rule from the course: read each workflow status separately, and inspect the failing step before changing application code.

## 9. Course demo without AWS: Cloudflare Quick Tunnel

`deploy/scripts/demo-tunnel.sh` runs `cloudflared tunnel --url http://localhost:8080` and prints the constraints: temporary random URL, no account and no SLA, no authentication at the edge (keep `AUTH_MODE=oidc` or accept that every visitor is `dev-operator`), data stays on the laptop (so it demonstrates Phases 2–3, not 7), WebSocket works with added latency, stop with Ctrl-C. This is the fallback for presenting Weekend 4 while the AWS account is pending; it is not a deployment.
