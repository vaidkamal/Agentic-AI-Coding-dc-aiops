#!/usr/bin/env bash
# restore.sh — Phase 7 step 3: rebuild from a snapshot and PROVE the data came back.
#
# Proof (backend-spec §8): the same INC-nnn, with its original `opened` timestamp, is
# retrievable from the rebuilt API. This script prints PASS or FAIL on its last line.
#
# Steps:
#   1. terraform apply -var snapshot_identifier=<snap>   (RDS created FROM the snapshot)
#   2. gh workflow run deploy.yml                         (ECR is empty after destroy;
#                                                          the workflow rebuilds + pushes
#                                                          the image and rolls it out)
#   3. wait for that run to finish
#   4. GET $API_BASE/incidents and look for the known incident id (+ opened timestamp)
#
# Usage:
#   deploy/scripts/restore.sh <snapshot-id|last> <INC-nnn> [expected-opened-ISO]
#   e.g. deploy/scripts/restore.sh last INC-101 2026-10-17T15:42:10Z
#
# Needs: terraform, aws, gh (authenticated), curl, jq. TF_VAR_db_password exported.
#        SMOKE_TOKEN (bearer accepted by the hosted API) exported for the GET.
#        API_BASE defaults to /api/v1 (set API_BASE=/api while the backend still serves that).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$HERE/../terraform"
STAMP_FILE="$HERE/../.last-snapshot"
API_BASE="${API_BASE:-/api/v1}"
WORKFLOW="deploy.yml"
BRANCH="${DEPLOY_BRANCH:-main}"

log() { printf '[restore] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; echo "FAIL"; exit 1; }

for t in terraform aws gh curl jq; do command -v "$t" >/dev/null || die "$t not found"; done

SNAP_ARG="${1:-}"; INC_ID="${2:-}"; EXPECT_OPENED="${3:-}"
[ -n "$SNAP_ARG" ] && [ -n "$INC_ID" ] || die "usage: $0 <snapshot-id|last> <INC-nnn> [opened-ISO]"
[[ "$INC_ID" =~ ^INC-[0-9]+$ ]] || die "incident id must match INC-<digits>, got '$INC_ID'"
[ -n "${TF_VAR_db_password:-}" ] || die "TF_VAR_db_password must be exported (same password the snapshot was taken with)"

if [ "$SNAP_ARG" = "last" ]; then
  [ -f "$STAMP_FILE" ] || die "no $STAMP_FILE; pass the snapshot id explicitly"
  SNAP_ID="$(cat "$STAMP_FILE")"
else
  SNAP_ID="$SNAP_ARG"
fi

SNAP_STATUS="$(aws rds describe-db-snapshots --db-snapshot-identifier "$SNAP_ID" \
               --query 'DBSnapshots[0].Status' --output text 2>/dev/null || true)"
[ "$SNAP_STATUS" = "available" ] || die "snapshot '$SNAP_ID' status is '${SNAP_STATUS:-not found}'"
log "snapshot : $SNAP_ID (available)"
log "incident : $INC_ID ${EXPECT_OPENED:+(opened $EXPECT_OPENED)}"

# ------------------------------------------------------- 1. rebuild infra ----
log "step 1/4: terraform apply from snapshot"
terraform -chdir="$TF_DIR" init -input=false >/dev/null
terraform -chdir="$TF_DIR" apply -input=false -auto-approve \
  -var "snapshot_identifier=$SNAP_ID" \
  || die "terraform apply failed"

ALB_URL="$(terraform -chdir="$TF_DIR" output -raw alb_url)"
CONSOLE_URL="$(terraform -chdir="$TF_DIR" output -raw console_url)"
log "ALB     : $ALB_URL"
log "console : $CONSOLE_URL  (NEW hostname - update the frontend/IdP redirect URI)"

# ---------------------------------------------------- 2. re-publish image ----
log "step 2/4: trigger $WORKFLOW on $BRANCH (ECR is empty after destroy)"
gh workflow run "$WORKFLOW" --ref "$BRANCH" -f reason="Phase 7 restore from $SNAP_ID" \
  || die "gh workflow run failed (is gh authenticated and the repo set?)"

# ---------------------------------------------------- 3. wait for the run ----
log "step 3/4: wait for the workflow run"
sleep 10   # GitHub needs a moment before the run is listed
RUN_ID="$(gh run list --workflow "$WORKFLOW" --branch "$BRANCH" --event workflow_dispatch \
          --limit 1 --json databaseId --jq '.[0].databaseId')"
[ -n "$RUN_ID" ] || die "could not find the dispatched run"
log "run id: $RUN_ID - $(gh run view "$RUN_ID" --json url --jq .url)"
gh run watch "$RUN_ID" --exit-status || die "deploy run $RUN_ID failed - inspect the failing step before changing anything"

# ------------------------------------------------------- 4. prove restore ----
log "step 4/4: GET $API_BASE/incidents and look for $INC_ID"
RESP="$(curl -fsS --max-time 15 "$ALB_URL$API_BASE/incidents" \
        -H "Authorization: Bearer ${SMOKE_TOKEN:-}")" \
  || die "GET $ALB_URL$API_BASE/incidents failed"

MATCH="$(printf '%s' "$RESP" | jq -c --arg id "$INC_ID" '.[] | select(.id == $id)')"
if [ -z "$MATCH" ]; then
  log "incident $INC_ID NOT found. Ids present: $(printf '%s' "$RESP" | jq -r '[.[].id] | join(", ")')"
  echo "FAIL"; exit 1
fi

OPENED="$(printf '%s' "$MATCH" | jq -r '.opened')"
log "found $INC_ID opened=$OPENED resolved=$(printf '%s' "$MATCH" | jq -r '.resolved')"

if [ -n "$EXPECT_OPENED" ] && [ "$OPENED" != "$EXPECT_OPENED" ]; then
  log "opened timestamp differs: expected $EXPECT_OPENED, got $OPENED"
  echo "FAIL"; exit 1
fi

log "restore proof: $INC_ID with original opened=$OPENED retrievable after rebuild"
echo "PASS"
