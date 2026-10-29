#!/usr/bin/env bash
# Delete every VM and the firewall rule created by deploy.sh (stops billing).
set -euo pipefail
NAMES=$(gcloud compute instances list --filter='name~^(master|worker)' --format='value(name)' | tr '\n' ' ')
# shellcheck disable=SC2086
[ -n "$NAMES" ] && gcloud compute instances delete $NAMES --quiet
gcloud compute firewall-rules delete parcs-ui --quiet || true
