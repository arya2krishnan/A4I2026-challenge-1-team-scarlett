#!/usr/bin/env bash
# Roll the Toolbox back to an earlier set of tool definitions.
#   bash scripts/rollback_toolbox.sh 7    # v2 model, original data   (live 21:59-22:45 UTC, 2026-11-17)
#   bash scripts/rollback_toolbox.sh 6    # original model            (before 21:59 UTC)
# Both Toolbox services mount the secret's :latest, so routing traffic to an old revision is NOT enough:
# this re-adds the chosen version as the new latest, then forces a fresh us-central1 revision to load it.
# (Simplest path back to "v2, original data": bash scripts/deploy_toolbox.sh, which deploys toolbox/tools.yaml.)
set -euo pipefail
. "$(dirname "$0")/_env.sh"
VERSION="${1:?usage: $0 <secret version to restore>}"
SERVICE="${TOOLBOX_SERVICE_NAME:-heat-toolbox}"; SECRET="${SERVICE}-tools"
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
gcloud secrets versions access "$VERSION" --secret "$SECRET" --project "$PROJECT" > "$TMP"
grep -o -E '\.(heat_offset[a-z_]*|site_context[a-z_]*)`' "$TMP" | sort | uniq -c | sed 's/^/>> restoring: /'
gcloud secrets versions add "$SECRET" --project "$PROJECT" --data-file="$TMP" >/dev/null
gcloud run services update "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --update-labels "tools-version=restored-v$VERSION" --quiet
echo ">> $SERVICE now serves secret version $VERSION's definitions (as a new latest version)."
