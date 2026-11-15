#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <gcp-project-id>" >&2
  exit 2
fi
PROJECT="$1"
REGION="${BATON_REGION:-us-central1}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

gcloud run deploy baton-docs --source "$ROOT/docs-site" --project "$PROJECT" --region "$REGION" \
  --cpu 1 --memory 256Mi --min-instances 0 --max-instances 1 --concurrency 80 \
  --allow-unauthenticated --quiet

gcloud run services describe baton-docs --project "$PROJECT" --region "$REGION" --format='value(status.url)'
