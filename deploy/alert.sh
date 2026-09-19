#!/usr/bin/env bash
set -euo pipefail
set -a
source /opt/job-intel/worker.env
set +a
: "${JOB_INTEL_ALERT_TOPIC:?Configure an owner-only alert topic before enabling schedules}"
aws sns publish --topic-arn "$JOB_INTEL_ALERT_TOPIC" --subject "Job Intel needs attention" --message "Job Intel scheduled work failed or a source is stale. Inspect the private worker logs; no candidate data is included in this alert." >/dev/null
