#!/usr/bin/env bash
# One-time, idempotent: enable APIs and create/grant the service accounts. Needs project admin; skip what your admin did.
set -euo pipefail
. "$(dirname "$0")/_env.sh"
echo ">> Enabling APIs"
gcloud services enable --project "$PROJECT" aiplatform.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com bigquery.googleapis.com secretmanager.googleapis.com logging.googleapis.com \
  cloudtrace.googleapis.com

mk_sa() {  # email display
  gcloud iam service-accounts describe "$1" --project "$PROJECT" >/dev/null 2>&1 || \
    gcloud iam service-accounts create "${1%%@*}" --project "$PROJECT" --display-name "$2"
}
TB_SA="${TOOLBOX_SERVICE_ACCOUNT:-heat-toolbox@${PROJECT}.iam.gserviceaccount.com}"
AG_SA="${AGENT_SERVICE_ACCOUNT:-heat-agent@${PROJECT}.iam.gserviceaccount.com}"
mk_sa "$TB_SA" "Heat toolbox (Cloud Run)"; mk_sa "$AG_SA" "Heat dispatch agent (Agent Runtime)"
save_env TOOLBOX_SERVICE_ACCOUNT "$TB_SA"; save_env AGENT_SERVICE_ACCOUNT "$AG_SA"

bind() { retry gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$1" --role "$2" --condition=None --quiet >/dev/null; }
echo ">> Toolbox identity $TB_SA: reads the dataset (read-only), runs query jobs, reads its config secret"
bind "$TB_SA" roles/bigquery.jobUser; bind "$TB_SA" roles/bigquery.dataViewer; bind "$TB_SA" roles/secretmanager.secretAccessor
CL_SA="${CLIENT_SERVICE_ACCOUNT:-heat-client@${PROJECT}.iam.gserviceaccount.com}"
mk_sa "$CL_SA" "Heat dispatch client (Cloud Run)"; save_env CLIENT_SERVICE_ACCOUNT "$CL_SA"
bind "$CL_SA" roles/aiplatform.user       # lets the client call the deployed agent
echo ">> Agent identity $AG_SA: Gemini + logs/traces"
for r in roles/aiplatform.user roles/logging.logWriter roles/cloudtrace.agent roles/monitoring.metricWriter; do bind "$AG_SA" "$r"; done
echo "Done. Next: gcloud auth application-default login && gcloud auth application-default set-quota-project $PROJECT"
echo "Note: the agent's right to call the private Toolbox service (run.invoker) is granted by 'make deploy-toolbox'."
