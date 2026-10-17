#!/usr/bin/env bash
# destroy.sh — Phase 7 step 2: backup FIRST, then `terraform destroy`.
#
# Order is the whole point: the manual snapshot must be "available" before any resource
# is removed. If backup.sh exits non-zero this script stops immediately and nothing is
# destroyed. RDS also takes a final snapshot on delete (skip_final_snapshot = false), but
# that is a safety net, not the plan.
#
# Usage:
#   deploy/scripts/destroy.sh            # interactive: prints the plan, asks for "destroy"
#   deploy/scripts/destroy.sh --yes      # non-interactive (CI / rehearsed demo)
#
# What survives: S3 state + DynamoDB lock (outside this config), RDS snapshots, the DB
# password you hold, the GitHub secrets. Everything else is gone. See deployment-brief.md.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$HERE/../terraform"
AUTO="${1:-}"

log() { printf '[destroy] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

command -v terraform >/dev/null || die "terraform not found"
command -v aws >/dev/null || die "aws CLI not found"

# ---------------------------------------------------------------- 1. backup ----
log "step 1/3: manual RDS snapshot (must succeed or we stop here)"
if ! SNAP_ID="$("$HERE/backup.sh" | tail -n 1)"; then
  die "backup.sh failed - refusing to destroy anything. Fix the backup, then re-run."
fi
[ -n "$SNAP_ID" ] || die "backup.sh returned no snapshot id - refusing to destroy."
log "backup OK: $SNAP_ID"

# ------------------------------------------------------------- 2. show plan ----
log "step 2/3: terraform plan -destroy"
terraform -chdir="$TF_DIR" init -input=false >/dev/null
terraform -chdir="$TF_DIR" plan -destroy -input=false -out="$TF_DIR/destroy.tfplan"

if [ "$AUTO" != "--yes" ]; then
  cat >&2 <<EOF

  About to destroy the stack above.
  Restore later with:
    deploy/scripts/restore.sh $SNAP_ID <INC-nnn>

EOF
  read -r -p "Type 'destroy' to continue: " ANSWER
  [ "$ANSWER" = "destroy" ] || die "aborted by operator; nothing destroyed. Snapshot $SNAP_ID kept."
fi

# ---------------------------------------------------------------- 3. destroy ----
log "step 3/3: terraform apply destroy.tfplan"
terraform -chdir="$TF_DIR" apply -input=false "$TF_DIR/destroy.tfplan"
rm -f "$TF_DIR/destroy.tfplan"

log "destroyed. Kept: snapshot $SNAP_ID, remote state, DB password (yours), GitHub secrets."
log "next: deploy/scripts/restore.sh $SNAP_ID <INC-nnn>"
