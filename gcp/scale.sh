#!/usr/bin/env bash
# Leave exactly N workers running (stop the rest). The master drops a stopped
# worker from its list after a missed heartbeat (~5 s).
#   ./gcp/scale.sh 2
set -euo pipefail
N="$1"
ALL=$(gcloud compute instances list --filter='name~^worker' --format='value(name)' | sort -V)
KEEP=$(echo "$ALL" | head -n "$N" | tr '\n' ' ')
STOP=$(echo "$ALL" | tail -n +"$((N + 1))" | tr '\n' ' ')
# shellcheck disable=SC2086
[ -n "$KEEP" ] && gcloud compute instances start $KEEP --quiet 2>/dev/null || true
# shellcheck disable=SC2086
[ -n "$STOP" ] && gcloud compute instances stop $STOP --quiet || true
gcloud compute instances list --filter='name~^(master|worker)'
