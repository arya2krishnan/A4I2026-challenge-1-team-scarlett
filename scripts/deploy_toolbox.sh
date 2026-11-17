#!/usr/bin/env bash
# Deploy MCP Toolbox to Cloud Run: private (IAM), one warm instance (no cold start on stage), config from Secret Manager.
set -euo pipefail
. "$(dirname "$0")/_env.sh"
SERVICE="${TOOLBOX_SERVICE_NAME:-heat-toolbox}"
SECRET="${SERVICE}-tools"
IMAGE="${TOOLBOX_IMAGE:-us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:latest}"
TB_SA="${TOOLBOX_SERVICE_ACCOUNT:-heat-toolbox@${PROJECT}.iam.gserviceaccount.com}"
AG_SA="${AGENT_SERVICE_ACCOUNT:-}"

TOOLS_SRC="${TOOLS_SRC:-$ROOT/toolbox/tools.yaml}"   # e.g. TOOLS_SRC=toolbox/tools.enriched.yaml
echo ">> tool definitions: $TOOLS_SRC"
"$PY" "$ROOT/scripts/render_toolbox.py" --src "$TOOLS_SRC" --out "$ROOT/toolbox/tools.rendered.yaml"
echo ">> uploading tool definitions to Secret Manager ($SECRET)"
if gcloud secrets describe "$SECRET" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud secrets versions add "$SECRET" --project "$PROJECT" --data-file="$ROOT/toolbox/tools.rendered.yaml" >/dev/null
else
  gcloud secrets create "$SECRET" --project "$PROJECT" --data-file="$ROOT/toolbox/tools.rendered.yaml" >/dev/null
fi

echo ">> deploying $SERVICE"
gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --image "$IMAGE" \
  --service-account "$TB_SA" --min-instances 1 --no-allow-unauthenticated \
  --set-secrets "/app/tools.yaml=${SECRET}:latest" \
  --args="--config=/app/tools.yaml","--address=0.0.0.0","--port=8080"
URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
save_env TOOLBOX_URL "$URL"
echo ">> Toolbox URL: $URL (saved to .env as TOOLBOX_URL)"

if [ -n "$AG_SA" ]; then
  gcloud run services add-iam-policy-binding "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --member "serviceAccount:$AG_SA" --role roles/run.invoker --quiet >/dev/null
  echo ">> granted run.invoker on $SERVICE to $AG_SA"
else
  NUM="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
  echo "!! AGENT_SERVICE_ACCOUNT is empty. Grant the agent's identity roles/run.invoker on $SERVICE, e.g. the default one:"
  echo "   gcloud run services add-iam-policy-binding $SERVICE --region $REGION --member serviceAccount:service-${NUM}@gcp-sa-aiplatform-re.iam.gserviceaccount.com --role roles/run.invoker"
fi
