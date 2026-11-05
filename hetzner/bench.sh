#!/usr/bin/env bash
# Benchmark the Hetzner cluster for 1..N worker processes (the SSH tunnel from
# `cluster.py tunnel` must be open on port 8081). Results: results/results_cloud.csv
set -euo pipefail
cd "$(dirname "$0")/.."
MAX="${1:-4}"; RUNS="${2:-3}"; MASTER="${MASTER:-http://localhost:8081}"
mkdir -p results/cloud
for n in $(seq 1 "$MAX"); do
  python3 hetzner/cluster.py scale "$n"
  python3 -u benchmark.py --master "$MASTER" --no-scale --workers "$n" --runs "$RUNS" --out "results/cloud/w$n.csv"
  cp "results/last_output_w$n.txt" "results/cloud/output_w$n.txt"
done
python3 hetzner/cluster.py scale "$MAX"
{ head -1 results/cloud/w1.csv; for n in $(seq 1 "$MAX"); do tail -n +2 "results/cloud/w$n.csv"; done; } > results/results_cloud.csv
echo "saved results/results_cloud.csv"
