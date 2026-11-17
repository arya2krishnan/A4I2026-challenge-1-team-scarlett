#!/usr/bin/env bash
# Deploy the Heat Dispatch Console (web/: React + FastAPI) to Cloud Run.
#
# Least privilege: the service runs as its own account (WEB_SERVICE_ACCOUNT, default heat-web@) with only
#   - roles/run.invoker on the Toolbox service          (all data reads go through MCP Toolbox)
#   - roles/aiplatform.user                             (query the agent on Agent Runtime + its sessions)
#   - roles/bigquery.jobUser                            (run the one query that reloads the latest plan)
#   - roles/bigquery.dataEditor on the TWO console tables only (dispatch_plan_versions, dispatch_approvals)
# No dataset-wide BigQuery access.
#
# Access: IAP on Cloud Run (WEB_IAP=true, default) so approvals carry the operator's email; grant people with
# WEB_USERS="user:a@x.org,group:desk@x.org". WEB_IAP=false falls back to Cloud Run IAM (use `gcloud run services proxy`).
# WEB_PUBLIC=true opens it to anyone with the link (judging): see the note next to AUTH below.
set -euo pipefail
. "$(dirname "$0")/_env.sh"
[ -n "${AGENT_RESOURCE_NAME:-}" ] || { echo "AGENT_RESOURCE_NAME is empty: run 'make deploy-agent' first." >&2; exit 1; }
[[ "${TOOLBOX_URL:-}" == https://* ]] || { echo "TOOLBOX_URL must be the deployed https URL: run 'make deploy-toolbox' first." >&2; exit 1; }
SERVICE="${WEB_SERVICE_NAME:-heat-dispatch-web}"
TB_SERVICE="${TOOLBOX_SERVICE_NAME:-heat-toolbox}"
SA="${WEB_SERVICE_ACCOUNT:-heat-web@${PROJECT}.iam.gserviceaccount.com}"
IAP="${WEB_IAP:-true}"

echo ">> service account $SA"
gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "${SA%%@*}" --project "$PROJECT" --display-name "Heat dispatch console (Cloud Run)"
save_env WEB_SERVICE_ACCOUNT "$SA"
for r in roles/aiplatform.user roles/bigquery.jobUser; do
  retry gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role "$r" --condition=None --quiet >/dev/null
done
retry gcloud run services add-iam-policy-binding "$TB_SERVICE" --project "$PROJECT" --region "$REGION" \
  --member "serviceAccount:$SA" --role roles/run.invoker --quiet >/dev/null

echo ">> console tables in $PROJECT:$BQ_DATASET"
for t in dispatch_plan_versions dispatch_approvals; do
  bq --location="$BQ_LOCATION" show "$PROJECT:$BQ_DATASET.$t" >/dev/null 2>&1 || \
    bq --location="$BQ_LOCATION" mk --table "$PROJECT:$BQ_DATASET.$t" "$ROOT/web/backend/schema/$t.json"
  retry bq add-iam-policy-binding --member="serviceAccount:$SA" --role=roles/bigquery.dataEditor "$PROJECT:$BQ_DATASET.$t" >/dev/null
done

BUILD="$(mktemp -d)"; trap 'rm -rf "$BUILD"' EXIT
mkdir -p "$BUILD/web/frontend" "$BUILD/agent/heat_dispatch"
cp "$ROOT/web/Dockerfile" "$BUILD/Dockerfile"
cp -R "$ROOT/web/backend" "$BUILD/web/backend"
( cd "$ROOT/web/frontend" && tar --exclude node_modules --exclude dist -cf - . ) | ( cd "$BUILD/web/frontend" && tar -xf - )
cp "$ROOT/agent/heat_dispatch/planner.py" "$BUILD/agent/heat_dispatch/planner.py"
find "$BUILD" -name __pycache__ -prune -exec rm -rf {} +

# WEB_PUBLIC=true: anyone with the link can open it (no login), e.g. for judges. It can call Gemini and BigQuery and its
# approve/undo actions write rows, so switch back to private (WEB_PUBLIC=false make deploy-web) when the event is over.
# --no-iap is explicit because gcloud keeps a previously enabled IAP setting on redeploy.
if [ "${WEB_PUBLIC:-false}" = "true" ]; then IAP=false; AUTH=(--allow-unauthenticated --no-iap)
elif [ "$IAP" = "true" ]; then AUTH=(--no-allow-unauthenticated --iap)
else AUTH=(--no-allow-unauthenticated --no-iap); fi
echo ">> deploying $SERVICE (IAP=$IAP)"
# max-instances=1: the board keeps the live plan in memory (BigQuery is the durable copy reloaded on start).
gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --source "$BUILD" --service-account "$SA" \
  --max-instances 1 --min-instances 0 --timeout 3600 --memory 1Gi "${AUTH[@]}" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=$REGION,BQ_DATASET=$BQ_DATASET,TOOLBOX_URL=$TOOLBOX_URL,AGENT_RESOURCE_NAME=$AGENT_RESOURCE_NAME,WEB_STORE=bigquery"
URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
save_env WEB_URL "$URL"

if [ "$IAP" = "true" ]; then
  NUM="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
  # IAP's service agent must be allowed to invoke the service it fronts.
  gcloud run services add-iam-policy-binding "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --member "serviceAccount:service-${NUM}@gcp-sa-iap.iam.gserviceaccount.com" --role roles/run.invoker --quiet >/dev/null
  for m in $(echo "${WEB_USERS:-}" | tr ',' ' '); do      # (bash 3.2 + set -u: no empty arrays)
    gcloud iap web add-iam-policy-binding --project "$PROJECT" --region "$REGION" --resource-type cloud-run \
      --service "$SERVICE" --member "$m" --role roles/iap.httpsResourceAccessor --quiet >/dev/null && echo ">> IAP access: $m"
  done
  echo ">> $URL  (IAP: sign in with a Google account listed in WEB_USERS)"
elif [ "${WEB_PUBLIC:-false}" = "true" ]; then
  echo ">> $URL  (PUBLIC: no login. WEB_PUBLIC=false to make it private again)"
else
  echo ">> $URL  (IAM-protected: gcloud run services proxy $SERVICE --project $PROJECT --region $REGION --port 8080)"
fi
