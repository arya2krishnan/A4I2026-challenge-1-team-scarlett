#!/usr/bin/env bash
# Deploy the dispatch approval API (api/) to Cloud Run, private, backed by Firestore. Idempotent: safe to re-run.
#   1. enable APIs   2. named Firestore database (does not touch the project's (default) database)
#   3. service account with Firestore read/write only   4. signing key in Secret Manager (created once, never printed)
#   5. gcloud run deploy --source api   6. save DISPATCH_API_URL to .env
set -euo pipefail
. "$(dirname "$0")/_env.sh"
SERVICE="${DISPATCH_API_SERVICE_NAME:-heat-dispatch-api}"
DB="${FIRESTORE_DATABASE:-heat-dispatch}"
DB_LOCATION="${FIRESTORE_LOCATION:-$REGION}"
SECRET="${DISPATCH_SIGNING_SECRET:-dispatch-signing-key}"
SA="${DISPATCH_API_SERVICE_ACCOUNT:-heat-dispatch-api@${PROJECT}.iam.gserviceaccount.com}"

echo ">> Enabling APIs"
gcloud services enable --project "$PROJECT" run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com firestore.googleapis.com secretmanager.googleapis.com

echo ">> Firestore database '$DB' ($DB_LOCATION)"
if ! gcloud firestore databases describe --database "$DB" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud firestore databases create --database "$DB" --location "$DB_LOCATION" --type firestore-native --project "$PROJECT"
fi

echo ">> Service account $SA"
gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "${SA%%@*}" --project "$PROJECT" --display-name "Heat dispatch API (Cloud Run)"
retry gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role roles/datastore.user \
  --condition=None --quiet >/dev/null
save_env DISPATCH_API_SERVICE_ACCOUNT "$SA"

echo ">> Signing key secret '$SECRET'"
if ! gcloud secrets describe "$SECRET" --project "$PROJECT" >/dev/null 2>&1; then
  openssl rand -hex 32 | tr -d '\n' | gcloud secrets create "$SECRET" --project "$PROJECT" \
    --replication-policy automatic --data-file=-
fi
retry gcloud secrets add-iam-policy-binding "$SECRET" --project "$PROJECT" --member "serviceAccount:$SA" \
  --role roles/secretmanager.secretAccessor --condition=None --quiet >/dev/null

echo ">> Deploying $SERVICE"
AUTH="--no-allow-unauthenticated"; [ "${ALLOW_UNAUTHENTICATED:-false}" = "true" ] && AUTH="--allow-unauthenticated"
gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --source "$ROOT/api" --service-account "$SA" \
  --memory 512Mi --max-instances 3 \
  --set-env-vars "DISPATCH_STORE=firestore,GOOGLE_CLOUD_PROJECT=$PROJECT,FIRESTORE_DATABASE=$DB" \
  --set-secrets "DISPATCH_SIGNING_KEY=$SECRET:latest" $AUTH --quiet
URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
save_env DISPATCH_API_URL "$URL"
echo ">> $URL  (private: callers need roles/run.invoker)"
echo ">> Test it: make smoke-api"
