#!/usr/bin/env bash
# POST /api/dispatches/{id}/close : stand a dispatch down; it leaves the active list
#   bash scripts/dispatch_api/close.sh                                   # last dispatch
#   bash scripts/dispatch_api/close.sh disp-abc123 "heat day over" "Officer Miller"
. "$(dirname "$0")/_common.sh"
DID="${1:-$(recall DISPATCH_ID)}"
[ -n "$DID" ] || { echo "No dispatch_id: run approve.sh first or pass one" >&2; exit 1; }
DATA="$(jq -n --arg reason "${2:-heat day over}" --arg by "${3:-Officer Miller}" '{closed_by: $by, reason: $reason}')"
call POST "/api/dispatches/$DID/close" "$DATA"
expect 200
