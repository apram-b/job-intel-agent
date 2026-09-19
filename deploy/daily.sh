#!/usr/bin/env bash
set -euo pipefail
/opt/job-intel/current/deploy/run.sh worker
# Demo evaluation is optional and shares the same global US$3 reservation ledger.
/opt/job-intel/current/deploy/run.sh export-demo --seed-profile --output /app/data/public-demo
/opt/job-intel/current/deploy/run.sh evaluate --profile demo
/opt/job-intel/current/deploy/run.sh export-demo --output /app/data/public-demo
/opt/job-intel/current/deploy/publish-demo.sh
