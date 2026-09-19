#!/usr/bin/env bash
set -euo pipefail
worker_host=${1:?Pass the confirmed Lightsail hostname or static IP}
key_file=${2:?Pass the local SSH key file}
# Verify the host fingerprint independently on first connection. Keep this process running.
exec ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:15432:127.0.0.1:5432 -i "$key_file" "ubuntu@$worker_host"
