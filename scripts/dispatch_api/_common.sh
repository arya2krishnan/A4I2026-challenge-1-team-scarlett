# Sourced by the dispatch API test scripts. Needs curl and jq (macOS 15+ ships jq; else brew/apt install jq).
#
#   API_URL   base URL (default http://127.0.0.1:8080; for Cloud Run use DISPATCH_API_URL from .env)
#   NOAUTH=1  never send an identity token (default: send one for https URLs, i.e. Cloud Run)
#
# The last proposal_id / dispatch_id are remembered in .data/dispatch_api_state, so scripts can be run in order
# without copying ids around. Pass an id explicitly to override.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE="$ROOT/.data/dispatch_api_state"

command -v jq >/dev/null || { echo "jq is required (brew install jq)" >&2; exit 1; }

if [ -z "${API_URL:-}" ] && [ -f "$ROOT/.env" ]; then
  API_URL="$(grep -E '^DISPATCH_API_URL=' "$ROOT/.env" | tail -1 | cut -d= -f2- || true)"
fi
API_URL="${API_URL:-http://127.0.0.1:8080}"
API_URL="${API_URL%/}"

AUTH_HEADER=()
case "$API_URL" in
  https://*) if [ "${NOAUTH:-}" != "1" ]; then
               AUTH_HEADER=(-H "Authorization: Bearer $(gcloud auth print-identity-token)")
             fi ;;
esac

# remember KEY VALUE / recall KEY
remember() {
  mkdir -p "$(dirname "$STATE")"; touch "$STATE"
  grep -v "^$1=" "$STATE" > "$STATE.tmp" || true
  echo "$1=$2" >> "$STATE.tmp" && mv "$STATE.tmp" "$STATE"
}
recall() { [ -f "$STATE" ] && grep -E "^$1=" "$STATE" | tail -1 | cut -d= -f2- || true; }

# call METHOD PATH [JSON_BODY]
#   prints "HTTP <code>  METHOD URL" and the pretty JSON response; sets $STATUS and $BODY for the caller.
call() {
  local method="$1" path="$2" data="${3:-}" out
  local args=(-s -X "$method" -H "Content-Type: application/json" -w $'\n%{http_code}')
  [ -n "$data" ] && args+=(--data "$data")
  out="$(curl "${args[@]}" ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"} "$API_URL$path")" || {
    echo "Could not reach $API_URL (is the server running? make api-local)" >&2; exit 1; }
  STATUS="${out##*$'\n'}"
  BODY="${out%$'\n'*}"
  echo "HTTP $STATUS  $method $API_URL$path" >&2
  echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
}

# expect CODE: fail the script unless the last call returned CODE
expect() {
  if [ "$STATUS" != "$1" ]; then echo "!! expected HTTP $1, got $STATUS" >&2; return 1; fi
}
