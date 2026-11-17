#!/usr/bin/env bash
# POST /api/dispatches/approve : a human dispatcher approves -> signed dispatch_id, APPROVED
#   bash scripts/dispatch_api/approve.sh                                  # last proposal, stops 1,2, Officer Miller
#   bash scripts/dispatch_api/approve.sh prop-abc123 "Officer Lee" 1,3     # explicit proposal, approver, stops
#   TEAMS=1 bash scripts/dispatch_api/approve.sh                          # approve only wellness team 1 (default: all)
#   OVERRIDES='{"2": {"latitude": 41.895, "longitude": -87.76, "reason": "hydrant work"}}' \
#     bash scripts/dispatch_api/approve.sh                                # move stop 2 at approval time
. "$(dirname "$0")/_common.sh"
PID="${1:-$(recall PROPOSAL_ID)}"
[ -n "$PID" ] || { echo "No proposal_id: run propose.sh first or pass one" >&2; exit 1; }
BY="${2:-Officer Miller}"
STOPS="${3:-1,2}"
OV="${OVERRIDES:-}"; [ -n "$OV" ] || OV='{}'
DATA="$(jq -n --arg pid "$PID" --arg by "$BY" --arg stops "$STOPS" --arg teams "${TEAMS:-}" \
          --argjson ov "$OV" '
  {proposal_id: $pid, approved_by: $by, approved_stops: ($stops | split(",") | map(tonumber)), overrides: $ov}
  + (if $teams == "" then {} else {approved_teams: ($teams | split(",") | map(tonumber))} end)')"
call POST /api/dispatches/approve "$DATA"
expect 201
DID="$(echo "$BODY" | jq -r .dispatch_id)"
remember DISPATCH_ID "$DID"
echo ">> dispatch_id=$DID saved (override.sh / close.sh will use it)" >&2
