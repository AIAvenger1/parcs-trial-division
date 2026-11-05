#!/usr/bin/env bash
# README.md -> report/report.pdf (pandoc + xelatex, macOS fonts)
set -euo pipefail
cd "$(dirname "$0")/.."
tail -n +2 README.md > report/body.md          # drop the H1, the title page has it
pandoc -f markdown+autolink_bare_uris report/title.md report/body.md -o report/report.pdf \
  --pdf-engine=xelatex --toc -V toc-title="Зміст" --resource-path=.
rm report/body.md
echo "report/report.pdf"
