#!/usr/bin/env bash
# backup.sh — Phase 7 step 1: take a manual RDS snapshot and WAIT until it is available.
#
# Contract: exits 0 only when a snapshot exists in status "available". Any other outcome
# exits non-zero, so a controlling script (destroy.sh) must stop. "If backup fails, the
# controlling script must stop."
#
# Usage:
#   deploy/scripts/backup.sh [db-instance-identifier]
# The identifier defaults to `terraform output -raw rds_identifier` or $RDS_IDENTIFIER.
# Prints the snapshot id on the last line of stdout and writes it to deploy/.last-snapshot
# so destroy.sh / restore.sh can pick it up without copy-paste errors.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$HERE/../terraform"
STAMP_FILE="$HERE/../.last-snapshot"

log() { printf '[backup] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

command -v aws >/dev/null || die "aws CLI not found"

DB_ID="${1:-${RDS_IDENTIFIER:-}}"
if [ -z "$DB_ID" ] && command -v terraform >/dev/null; then
  DB_ID="$(terraform -chdir="$TF_DIR" output -raw rds_identifier 2>/dev/null || true)"
fi
[ -n "$DB_ID" ] || die "no DB identifier: pass it as arg 1, set RDS_IDENTIFIER, or terraform apply first"

# Snapshot ids: letters, digits, hyphens only; must be unique → UTC timestamp.
SNAP_ID="${DB_ID}-manual-$(date -u +%Y%m%dT%H%M%SZ)"

log "instance : $DB_ID"
log "snapshot : $SNAP_ID"

# Refuse to snapshot something that is not healthy; a snapshot of a broken instance
# would give false confidence.
STATUS="$(aws rds describe-db-instances --db-instance-identifier "$DB_ID" \
          --query 'DBInstances[0].DBInstanceStatus' --output text)" \
  || die "instance $DB_ID not found (is Terraform applied?)"
[ "$STATUS" = "available" ] || die "instance status is '$STATUS', expected 'available'"

aws rds create-db-snapshot \
  --db-instance-identifier "$DB_ID" \
  --db-snapshot-identifier "$SNAP_ID" \
  --tags Key=Project,Value=dc-aiops Key=Purpose,Value=pre-destroy \
  --query 'DBSnapshot.{id:DBSnapshotIdentifier,status:Status}' --output text >&2 \
  || die "create-db-snapshot failed"

log "waiting for snapshot to become available (typically 2-5 min for a micro instance)..."
# The waiter polls every 30 s for up to 30 min and exits non-zero on timeout/failure.
aws rds wait db-snapshot-available --db-snapshot-identifier "$SNAP_ID" \
  || die "waiter failed: snapshot $SNAP_ID did not become available"

# Trust but verify: read the final status explicitly rather than relying on the waiter alone.
FINAL="$(aws rds describe-db-snapshots --db-snapshot-identifier "$SNAP_ID" \
         --query 'DBSnapshots[0].[Status,PercentProgress,AllocatedStorage]' --output text)"
read -r FSTATUS FPROGRESS FSIZE <<<"$FINAL"
[ "$FSTATUS" = "available" ] || die "snapshot status is '$FSTATUS' (progress $FPROGRESS%)"

log "snapshot available: $SNAP_ID (progress ${FPROGRESS}%, ${FSIZE} GiB)"
printf '%s\n' "$SNAP_ID" > "$STAMP_FILE"
log "recorded in $STAMP_FILE"

# Last line of stdout = the snapshot id, so callers can do SNAP=$(backup.sh | tail -1).
printf '%s\n' "$SNAP_ID"
