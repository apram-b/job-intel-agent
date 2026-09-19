#!/usr/bin/env bash
set -euo pipefail
umask 077
set -a
source /opt/job-intel/worker.env
set +a
: "${JOB_INTEL_BACKUP_RECIPIENT:?Configure the owner age public recipient}"
: "${JOB_INTEL_BACKUP_BUCKET:?Configure the private backup bucket}"
backup_file=$(mktemp /opt/job-intel/shared/backup.XXXXXX.age)
trap 'rm -f "$backup_file"' EXIT
cd /opt/job-intel/current
docker compose --env-file /opt/job-intel/worker.env -f deploy/compose.yaml exec -T db pg_dump -U job_intel -d job_intel -Fc | age -r "$JOB_INTEL_BACKUP_RECIPIENT" -o "$backup_file"
aws s3 cp "$backup_file" "s3://$JOB_INTEL_BACKUP_BUCKET/daily/$(date -u +%Y-%m-%dT%H-%M-%SZ).dump.age" --only-show-errors
