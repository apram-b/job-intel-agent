#!/usr/bin/env bash
set -euo pipefail
cd /opt/job-intel/current
exec docker compose --env-file /opt/job-intel/worker.env -f deploy/compose.yaml run --rm worker "$@"
