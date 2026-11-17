#!/usr/bin/env bash
# PATCH /api/dispatches/{id}/override : midday triage moves one stop and logs why
#   bash scripts/dispatch_api/override.sh 2 41.8960 -87.7660 "intersection blocked"
#   bash scripts/dispatch_api/override.sh 2 41.8960 -87.7660 "intersection blocked" "Dispatcher Ruiz" disp-abc123
. "$(dirname "$0")/_common.sh"
if [ $# -lt 4 ]; then
  echo "usage: $0 STOP LATITUDE LONGITUDE REASON [REQUESTED_BY] [DISPATCH_ID]" >&2; exit 2
fi
DID="${6:-$(recall DISPATCH_ID)}"
[ -n "$DID" ] || { echo "No dispatch_id: run approve.sh first or pass one" >&2; exit 1; }
DATA="$(jq -n --argjson stop "$1" --argjson lat "$2" --argjson lon "$3" --arg reason "$4" --arg by "${5:-Dispatcher Ruiz}" \
          '{stop: $stop, latitude: $lat, longitude: $lon, reason: $reason, requested_by: $by}')"
call PATCH "/api/dispatches/$DID/override" "$DATA"
expect 200
