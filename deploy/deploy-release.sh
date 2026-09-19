#!/usr/bin/env bash
# Run on the private worker after CI has tested and published this immutable release.
set -euo pipefail
release=${1:?Pass the full tested commit SHA}
[[ "$release" =~ ^[0-9a-f]{40}$ ]] || { echo 'Expected a full commit SHA'; exit 2; }
cd /opt/job-intel
old_release=$(readlink -f current)
# The release directory is uploaded by CI, not fetched from an unverified branch.
test -f "releases/$release/deploy/compose.yaml"
"$old_release/deploy/backup.sh"
cp worker.env worker.env.previous
sed -i "s|^JOB_INTEL_IMAGE=.*|JOB_INTEL_IMAGE=ghcr.io/apram-b/job-intel-agent:$release|" worker.env
chmod 600 worker.env
if ! docker compose --env-file worker.env -f "releases/$release/deploy/compose.yaml" pull worker; then
  mv worker.env.previous worker.env
  exit 1
fi
ln -sfn "$old_release" previous
ln -sfn "/opt/job-intel/releases/$release" current
if ! current/deploy/run.sh migrate; then
  mv worker.env.previous worker.env
  ln -sfn "$old_release" current
  echo 'Migration failed; previous release restored. Inspect before retrying.'
  exit 1
fi
# Additive migrations retain the old app's tables for rollback.
install -m 644 current/deploy/systemd/* /etc/systemd/system/
systemctl daemon-reload
current/deploy/run.sh health || echo 'Data freshness needs attention; inspect scan health before publication.'
