#!/usr/bin/env bash
# Deploy the agent to Agent Platform (Agent Runtime).
#   make deploy-agent            # updates the instance named in .env, or creates one
#   make deploy-agent NEW=1      # force a new instance
set -euo pipefail
. "$(dirname "$0")/_env.sh"
LOG="$(mktemp)"; ENVFILE="$ROOT/agent/heat_dispatch/.env"
trap 'rm -f "$LOG" "$ENVFILE"' EXIT
[ -n "${TOOLBOX_URL:-}" ] && [[ "$TOOLBOX_URL" == https://* ]] || { echo "TOOLBOX_URL must be the deployed https URL: run 'make deploy-toolbox' first." >&2; exit 1; }

# Baked into the deployed agent. Agent Runtime rejects empty values and manages GOOGLE_CLOUD_PROJECT/LOCATION itself.
printf '%s\n' "GOOGLE_GENAI_USE_ENTERPRISE=1" "MODEL=${MODEL:-gemini-3.6-flash}" "MODEL_LOCATION=${MODEL_LOCATION:-global}" \
  "TOOLBOX_URL=$TOOLBOX_URL" "TOOLBOX_TOOLSET=${TOOLBOX_TOOLSET:-heat_dispatch}" "MAPS_API_KEY=${MAPS_API_KEY:-}" | sed '/=$/d' > "$ENVFILE"

args=(--project "$PROJECT" --region "$REGION" --display_name "heat-dispatch-agent"
      --description "Chicago emergency heat dispatch assistant")
[ -n "${AGENT_SERVICE_ACCOUNT:-}" ] && args+=(--service_account "$AGENT_SERVICE_ACCOUNT")
if [ -z "${NEW:-}" ] && [ -n "${AGENT_RESOURCE_NAME:-}" ] && [[ "$AGENT_RESOURCE_NAME" == *"/locations/$REGION/"* ]]; then
  echo ">> updating $AGENT_RESOURCE_NAME"; args+=(--agent_engine_id "${AGENT_RESOURCE_NAME##*/}")
fi
( cd "$ROOT/agent" && "$ADK" deploy agent_engine "${args[@]}" heat_dispatch ) 2>&1 | tee "$LOG" >&2
RES="$(grep 'Deployed to Agent Platform' "$LOG" | grep -Eo 'projects/[0-9a-z-]+/locations/[a-z0-9-]+/reasoningEngines/[0-9]+' | tail -1 || true)"
[ -n "$RES" ] || { echo "!! could not read the resource name from the deploy output" >&2; exit 1; }
save_env AGENT_RESOURCE_NAME "$RES"; echo ">> agent: $RES (saved to .env as AGENT_RESOURCE_NAME)"
