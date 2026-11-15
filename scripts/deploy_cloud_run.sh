#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <gcp-project-id>" >&2
  exit 2
fi
PROJECT="$1"
REGION="${BATON_REGION:-us-central1}"
SERVICE="${BATON_SERVICE:-baton}"
MEMORY="${BATON_MEMORY:-2Gi}"
REPO=cloud-run-source-deploy
CLOUD_RUN_SERVICE_ID=152E-C115-5142
CAP_NAME="$SERVICE-cloud-run-spend-cap"
ALERT_NAME="$SERVICE-any-charge-alert"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

LEARN_TOKEN="${BATON_LEARN_TOKEN:-$(sed -n 's/^BATON_LEARN_TOKEN=//p' "$ROOT/.env" 2>/dev/null || true)}"
if [[ -z "$LEARN_TOKEN" ]]; then
  echo "set BATON_LEARN_TOKEN or add it to .env" >&2
  exit 1
fi

BILLING="$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)')"
if [[ -z "$BILLING" ]]; then
  echo "project $PROJECT has no billing account linked: gcloud billing projects link $PROJECT --billing-account=<id>" >&2
  exit 1
fi
BILLING_ID="${BILLING#billingAccounts/}"
CURRENCY="$(gcloud billing accounts describe "$BILLING_ID" --format='value(currencyCode)')"
CAP="${BATON_SPEND_CAP:-}"
if [[ -z "$CAP" && "$CURRENCY" == USD ]]; then
  CAP=1
fi
if [[ -z "$CAP" ]]; then
  echo "billing account currency is $CURRENCY: set BATON_SPEND_CAP to about 1 USD in $CURRENCY (whole units)" >&2
  exit 1
fi

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  billingbudgets.googleapis.com --project "$PROJECT"
BUILD_SA="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$BUILD_SA" \
  --role=roles/run.builder --condition=None --quiet >/dev/null

budgets="$(gcloud billing budgets list --billing-project "$PROJECT" --billing-account="$BILLING_ID" --format='value(displayName)')"
if ! grep -qx "$CAP_NAME" <<<"$budgets"; then
  cat > "$STAGE/cap.json" <<EOF
{
  "displayName": "$CAP_NAME",
  "budgetFilter": {
    "projects": ["projects/$PROJECT"],
    "services": ["services/$CLOUD_RUN_SERVICE_ID"],
    "creditTypesTreatment": "EXCLUDE_ALL_CREDITS",
    "calendarPeriod": "MONTH"
  },
  "amount": {"specifiedAmount": {"units": "$CAP"}},
  "thresholdRules": [{"thresholdPercent": 0.5}, {"thresholdPercent": 0.8}, {"thresholdPercent": 1.0}],
  "notificationsRule": {"enableProjectLevelRecipients": true},
  "spendCap": {"inputState": "CONFIGURED"}
}
EOF
  curl -sS --fail-with-body -X POST \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    -H "x-goog-user-project: $PROJECT" \
    -H "Content-Type: application/json" \
    -d @"$STAGE/cap.json" \
    "https://billingbudgets.googleapis.com/v1/billingAccounts/$BILLING_ID/budgets" >/dev/null
  echo "spend cap: Cloud Run pauses after $CAP $CURRENCY of gross usage this month"
fi
if ! grep -qx "$ALERT_NAME" <<<"$budgets"; then
  gcloud billing budgets create --billing-project "$PROJECT" --billing-account="$BILLING_ID" --display-name="$ALERT_NAME" \
    --budget-amount="$CAP$CURRENCY" --filter-projects="projects/$PROJECT" \
    --threshold-rule=percent=0.01 >/dev/null
  echo "alert: email on the first real charge to $PROJECT"
fi

if ! gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPO" --repository-format=docker --location "$REGION" --project "$PROJECT"
fi
cat > "$STAGE/cleanup.json" <<'EOF'
[
  {"name": "keep-latest", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 2}},
  {"name": "delete-rest", "action": {"type": "Delete"}, "condition": {"tagState": "any"}}
]
EOF
gcloud artifacts repositories set-cleanup-policies "$REPO" --location "$REGION" --project "$PROJECT" \
  --policy "$STAGE/cleanup.json" --no-dry-run >/dev/null

HYDRADB_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
printf 'BATON_LEARN_TOKEN: "%s"\nBATON_HYDRADB_TOKEN: "%s"\n' "$LEARN_TOKEN" "$HYDRADB_TOKEN" > "$STAGE/env.yaml"

gcloud run deploy "$SERVICE" --source "$ROOT" --project "$PROJECT" --region "$REGION" \
  --execution-environment gen2 --cpu 1 --memory "$MEMORY" --no-cpu-boost --cpu-throttling \
  --min-instances 0 --max-instances 1 --concurrency 80 \
  --allow-unauthenticated --env-vars-file "$STAGE/env.yaml" --quiet

gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)'
