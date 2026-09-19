#!/usr/bin/env bash
set -euo pipefail
set -a
source /opt/job-intel/worker.env
set +a
: "${JOB_INTEL_DEMO_BUCKET:?Configure the private demo bucket}"
# Upload only the allowlisted artifacts, never a directory containing private records.
for asset in data.json index.html health.json; do
  aws s3 cp "/opt/job-intel/shared/public-demo/$asset" "s3://$JOB_INTEL_DEMO_BUCKET/$asset" --cache-control max-age=300 --only-show-errors
done
