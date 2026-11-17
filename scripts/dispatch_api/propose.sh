#!/usr/bin/env bash
# POST /api/dispatches/proposals : the agent submits its recommendation sheet -> proposal_id, PENDING_REVIEW
#   bash scripts/dispatch_api/propose.sh                    # sends sample_proposal.json
#   bash scripts/dispatch_api/propose.sh my_plan.json       # any build_dispatch_plan output + forecast_high_f
. "$(dirname "$0")/_common.sh"
FILE="${1:-$(dirname "$0")/sample_proposal.json}"
[ -f "$FILE" ] || { echo "No such file: $FILE" >&2; exit 1; }
call POST /api/dispatches/proposals "$(cat "$FILE")"
expect 201
PID="$(echo "$BODY" | jq -r .proposal_id)"
remember PROPOSAL_ID "$PID"
echo ">> proposal_id=$PID saved (approve.sh will use it)" >&2
