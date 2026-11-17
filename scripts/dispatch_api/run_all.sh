#!/usr/bin/env bash
# Walk through every endpoint in order, including the calls that SHOULD fail, and stop at the first surprise.
#   bash scripts/dispatch_api/run_all.sh
#   API_URL=https://heat-dispatch-api-xxxx.run.app bash scripts/dispatch_api/run_all.sh    # against Cloud Run
. "$(dirname "$0")/_common.sh"
D="$(dirname "$0")"
step() { printf '\n\033[1m== %s\033[0m\n' "$*" >&2; }

step "1. health";                         bash "$D/health.sh"
step "2. agent submits a proposal";       bash "$D/propose.sh"
PID="$(recall PROPOSAL_ID)"

step "3. proposal outside Chicago -> 422"
call POST /api/dispatches/proposals "$(jq '.hydration_stops = [{stop: 1, latitude: 40.71, longitude: -74.0}]' "$D/sample_proposal.json")"
expect 422

step "4. approve a stop that is not in the proposal -> 422"
call POST /api/dispatches/approve "$(jq -n --arg p "$PID" '{proposal_id: $p, approved_by: "Officer Miller", approved_stops: [1, 9]}')"
expect 422

step "5. dispatcher approves stops 1,2 and moves stop 2"
OVERRIDES='{"2": {"latitude": 41.8950, "longitude": -87.7600, "reason": "hydrant work on the corner"}}' bash "$D/approve.sh" "$PID"
DID="$(recall DISPATCH_ID)"

step "6. approving the same proposal again -> 409"
call POST /api/dispatches/approve "$(jq -n --arg p "$PID" '{proposal_id: $p, approved_by: "Officer Lee", approved_stops: [1]}')"
expect 409

step "7. field crews read active dispatches"; SUMMARY=1 bash "$D/active.sh"

step "8. midday triage: truck #2 rerouted"
bash "$D/override.sh" 2 41.8960 -87.7660 "intersection blocked by a crash" "Dispatcher Ruiz" "$DID"

step "9. override a stop that was not approved -> 422"
call PATCH "/api/dispatches/$DID/override" '{"stop": 3, "latitude": 41.84, "longitude": -87.71, "reason": "x", "requested_by": "R"}'
expect 422

step "10. override an unknown dispatch -> 404"
call PATCH "/api/dispatches/disp-doesnotexist/override" '{"stop": 1, "latitude": 41.84, "longitude": -87.71, "reason": "x", "requested_by": "R"}'
expect 404

step "11. close the dispatch";            bash "$D/close.sh" "$DID" "demo finished" "Officer Miller"

step "12. override after close -> 409"
call PATCH "/api/dispatches/$DID/override" '{"stop": 1, "latitude": 41.84, "longitude": -87.71, "reason": "x", "requested_by": "R"}'
expect 409

step "13. active list no longer has it"; SUMMARY=1 bash "$D/active.sh"
call GET /api/dispatches/active >/dev/null; expect 200
if echo "$BODY" | jq -e --arg d "$DID" '.dispatches | map(.dispatch_id) | index($d) != null' >/dev/null; then
  echo "!! $DID is still active" >&2; exit 1
fi
printf '\n\033[1;32mAll endpoint checks behaved as expected.\033[0m\n' >&2
