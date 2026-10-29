#!/usr/bin/env bash
# Create a PARCS-Python cluster (1 master + N workers) in Google Compute Engine.
#
#   ./gcp/deploy.sh                 # 4 workers (default)
#   WORKERS=8 ./gcp/deploy.sh
#
# Requires: gcloud CLI, a project with billing enabled and Compute Engine API on.
set -euo pipefail

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
ZONE="${ZONE:-europe-central2-a}"
WORKERS="${WORKERS:-4}"
MACHINE_MASTER="${MACHINE_MASTER:-e2-small}"
MACHINE_WORKER="${MACHINE_WORKER:-e2-medium}"     # 1 shared-core vCPU is enough: the solver is single-threaded
IMAGE="${IMAGE:-ghcr.io/aiavenger1/parcs-node:latest}"
# Only your own IP may reach the web UI: it executes any uploaded code.
MY_IP="${MY_IP:-$(curl -s https://api.ipify.org)}"

echo ">> project=$PROJECT zone=$ZONE workers=$WORKERS image=$IMAGE"
gcloud config set compute/zone "$ZONE" >/dev/null

# 1. firewall: PARCS UI (8080) only from my IP; node-to-node traffic is already
#    allowed inside the default VPC by the default-allow-internal rule.
gcloud compute firewall-rules describe parcs-ui >/dev/null 2>&1 || \
gcloud compute firewall-rules create parcs-ui \
  --direction=INGRESS --network=default --action=ALLOW \
  --rules=tcp:8080 --source-ranges="$MY_IP/32" --target-tags=parcs-master

# 2. master
gcloud compute instances create-with-container master \
  --machine-type="$MACHINE_MASTER" --tags=parcs-master \
  --container-image="$IMAGE" --container-env=PARCS_ARGS="master"

MASTER_INT=$(gcloud compute instances describe master --format='get(networkInterfaces[0].networkIP)')
MASTER_EXT=$(gcloud compute instances describe master --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
echo ">> master internal=$MASTER_INT external=$MASTER_EXT"

# 3. workers (no external IP: they only talk to the master)
NAMES=$(seq -f "worker%g" 1 "$WORKERS" | tr '\n' ' ')
# shellcheck disable=SC2086
gcloud compute instances create-with-container $NAMES \
  --machine-type="$MACHINE_WORKER" --no-address \
  --container-image="$IMAGE" --container-env=PARCS_ARGS="worker $MASTER_INT"

echo
echo ">> PARCS UI:  http://$MASTER_EXT:8080"
echo ">> workers:   http://$MASTER_EXT:8080/workers   (registration takes ~30-60 s)"
echo ">> benchmark: python3 benchmark.py --master http://$MASTER_EXT:8080 --no-scale --workers $WORKERS"
