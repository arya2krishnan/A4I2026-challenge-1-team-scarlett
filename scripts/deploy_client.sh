#!/usr/bin/env bash
# Deploy the Streamlit client to Cloud Run. It holds no agent logic: it calls the deployed agent.
set -euo pipefail
. "$(dirname "$0")/_env.sh"
[ -n "${AGENT_RESOURCE_NAME:-}" ] || { echo "AGENT_RESOURCE_NAME is empty: run 'make deploy-agent' first." >&2; exit 1; }
SERVICE="${CLIENT_SERVICE_NAME:-heat-dispatch-client}"
SA="${CLIENT_SERVICE_ACCOUNT:-}"   # needs roles/aiplatform.user; empty = the Compute default account
BUILD="$(mktemp -d)"; trap 'rm -rf "$BUILD"' EXIT
cp -R "$ROOT/client/." "$BUILD/"
cat > "$BUILD/Dockerfile" <<'D'
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN useradd -m app && chown -R app /app
USER app
CMD ["sh", "-c", "exec streamlit run app.py --server.port=${PORT:-8080} --server.address=0.0.0.0"]
D
AUTH="--no-allow-unauthenticated"; [ "${ALLOW_UNAUTHENTICATED:-false}" = "true" ] && AUTH="--allow-unauthenticated"
gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --source "$BUILD" ${SA:+--service-account "$SA"} \
  --session-affinity --timeout 3600 --memory 1Gi \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=$REGION,AGENT_RESOURCE_NAME=$AGENT_RESOURCE_NAME" $AUTH
echo ">> $(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
echo ">> IAM-protected by default: gcloud run services proxy $SERVICE --project $PROJECT --region $REGION --port 8501"
