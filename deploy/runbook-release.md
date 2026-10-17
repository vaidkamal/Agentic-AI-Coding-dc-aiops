# Runbook — release, rollback, recovery

<!-- Weekend 4. Operator-run; nothing here executes on its own. Read the whole section before starting it. -->

Two rules from the course apply to every section:

1. **Read each workflow status separately.** The Deploy run has two jobs (`Check`, `Build, migrate, roll out, verify`) and the second has eight steps. A red run tells you nothing until you know *which* step went red.
2. **Inspect the failing step before changing application code.** Most release failures are configuration (a missing secret, a stale `ALB_URL`, an IAM condition), not the application. Changing code to chase an infrastructure error wastes the evidence.

## 0. Prerequisites (once)

- Phase 4 applied: `cd deploy/terraform && terraform apply` finished and `terraform output` works.
- GitHub secrets `AWS_DEPLOY_ROLE_ARN`, `ALB_URL`, `SMOKE_TOKEN`; variables `AWS_REGION`, `ECR_REPOSITORY`, `ECS_CLUSTER`, `ECS_SERVICE` (values from `terraform output`). Optional variable `API_BASE` (defaults to `/api/v1`).
- `gh auth status` succeeds locally; `aws sts get-caller-identity` shows the operator account.

## 1. Release (push to `main`)

| Step | Do | Expect | If not |
|---|---|---|---|
| 1.1 | `./scripts/verify.sh` locally. | Green. | Fix locally first. Never release to find out. |
| 1.2 | Merge/push to `main` (paths `backend/**`, `frontend/**`, `Dockerfile`). | A **Deploy** run appears in Actions. **CI** runs too, separately. | Nothing appears → the push touched no watched path; use §2. |
| 1.3 | Open the Deploy run. Read job **Check**. | Green. | Red here = the same failure `verify.sh` would show. Fix code, go to 1.1. |
| 1.4 | Read step **Configure AWS credentials**. | "Assumed role …". | `Not authorized to perform sts:AssumeRoleWithWebIdentity` → branch/repo does not match the IAM trust `sub`, or `AWS_DEPLOY_ROLE_ARN` is wrong. Fix in Terraform/GitHub, re-run; do not touch code. |
| 1.5 | Read **Build and push image**. | "Pushed …/dc-aiops:<sha>". | Docker build error → that *is* code (Dockerfile/requirements). ECR 403 → IAM policy `EcrPush`. |
| 1.6 | Read **Register task definition**. | "Registered arn:…:task-definition/dc-aiops-api:N". | `describe-services` empty → `ECS_CLUSTER`/`ECS_SERVICE` variables wrong. |
| 1.7 | Read **Run database migration**. | `migrate-result.json` shows `exitCode: 0`; "Migration exit code 0". | Non-zero: open CloudWatch log group `/ecs/dc-aiops`, stream `api/api/<task-id>`. Schema error → fix the migration (code). `CannotPullContainerError` → NAT/route/ECR permission (infra). The service was **not** touched; nothing to roll back. |
| 1.8 | Read **Update ECS service** and **Wait for service stability**. | Deployment table shows one `PRIMARY` with `running == desired`. | Timeout → ECS console → service → Events. `unhealthy` targets → `/healthz` failing in the new image (code) or port/SG mismatch (infra). Circuit breaker has already rolled back; confirm in Events. |
| 1.9 | Read **Health check on the ALB**. | `healthz OK: {"ok":true,…}`. | Wrong `ALB_URL` secret after a rebuild is the usual cause. |
| 1.10 | Read **Smoke test**. | `Smoke PASS: INC-9… created (201) and resolved (200, resolved=true)`. | 401 → `SMOKE_TOKEN` expired/invalid. 404 on `/api/v1` → `API_BASE` mismatch with the backend. 422 → contract change in the backend; check api-contract-spec before touching the workflow. |
| 1.11 | Record: run URL, image SHA, task-definition revision (in the run's Summary tab) in the phase log. | | |

## 2. Manual release / re-publish (workflow_dispatch)

Use after a Phase 7 rebuild (ECR is empty) or to redeploy the current `main` without a code change.

```
gh workflow run deploy.yml --ref main -f reason="<why>"
gh run watch $(gh run list --workflow deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status
```

Then read the steps exactly as in §1.3–1.11.

## 3. Reading a failed run (checklist)

1. Which **job** failed? `Check` → local problem. `Build, migrate, roll out, verify` → continue.
2. Which **step** failed? Expand only that step. Copy the last 20 lines into the incident note.
3. Classify: **auth/IAM** (AccessDenied, not authorized), **config** (wrong name/URL/secret), **infra** (timeouts, pull errors, unhealthy targets), **application** (traceback, 4xx/5xx from our API).
4. Only an **application** classification justifies a code change. Everything else is fixed in GitHub settings, Terraform, or AWS and then **re-run the same commit** (`gh run rerun <id>`), which also proves the fix.
5. Re-read the status after the re-run. Do not assume.

## 4. Rollback (service level, minutes)

The previous task-definition revision still exists and its image is still in ECR (lifecycle keeps 10).

```
CLUSTER=$(terraform -chdir=deploy/terraform output -raw ecs_cluster)
SERVICE=$(terraform -chdir=deploy/terraform output -raw ecs_service)
FAMILY=$(terraform -chdir=deploy/terraform output -raw task_definition_family)

aws ecs list-task-definitions --family-prefix "$FAMILY" --sort DESC --max-items 5   # pick the previous one
aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" --task-definition "$FAMILY:<N-1>"
aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"
curl -s "$(terraform -chdir=deploy/terraform output -raw alb_url)/healthz"
```

- If the bad release included a **migration**, rolling the service back may not be enough: the schema has moved. Decide between a forward fix (new migration) and a restore from the pre-release snapshot (§6). Taking `deploy/scripts/backup.sh` **before** any release with a migration is what makes the second option available.
- `terraform plan` stays clean after a rollback: the service ignores `task_definition`.
- Record what was rolled back, to which revision, and why.

## 5. Teardown (Phase 7, part 1)

```
export TF_VAR_db_password=<from password manager>
deploy/scripts/destroy.sh            # backup.sh runs first; stops if the snapshot is not 'available'
```

Read the output: the snapshot id is printed before the plan. If `backup.sh` fails, nothing has been destroyed — fix the backup (instance status, IAM, quota) and run again. Do **not** bypass with `terraform destroy` directly.

## 6. Restore (Phase 7, part 2)

```
export TF_VAR_db_password=<same password as before>
export SMOKE_TOKEN=<bearer accepted by the hosted API>
deploy/scripts/restore.sh last INC-101 2026-10-17T15:42:10Z     # or an explicit snapshot id
```

Expect the last line `PASS`. Then:

1. `terraform output console_url` — a **new** CloudFront hostname. Update the IdP redirect URI / allowed origin and any shared link.
2. Update GitHub secret `ALB_URL` from `terraform output alb_url`.
3. Open the console over HTTPS and look at the restored incident's timeline: the `opened` time must be the original. That screenshot plus the `PASS` line is the Phase 7 evidence.

`FAIL` cases: the workflow run failed → §3; the incident list is empty → the snapshot id was wrong or the backend is not reading `DATABASE_URL` (check `/healthz` → `db`); `opened` differs → the backend rewrote the timestamp on load — that is an application bug, report it against backend-spec §8.

## 7. Evidence to keep per phase

| Phase | Keep |
|---|---|
| 5 | Deploy run URL; image SHA; task-definition revision; `healthz` body; smoke PASS line. |
| 6 | Screenshot of the console at `https://…cloudfront.net` with an incident created and resolved. |
| 7 | `backup.sh` snapshot id; `destroy.sh` final lines; `restore.sh` `PASS` line with the incident id and `opened`. |
