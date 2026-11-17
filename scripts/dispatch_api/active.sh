#!/usr/bin/env bash
# GET /api/dispatches/active : what field crews and the dispatch map see
#   bash scripts/dispatch_api/active.sh             # full JSON
#   SUMMARY=1 bash scripts/dispatch_api/active.sh   # one line per truck stop / wellness team
. "$(dirname "$0")/_common.sh"
if [ "${SUMMARY:-}" = "1" ]; then
  call GET /api/dispatches/active >/dev/null
  expect 200
  echo "$BODY" | jq -r '
    "\(.count) active dispatch(es)",
    (.dispatches[] |
      "\n\(.dispatch_id)  rev \(.revision)  approved by \(.approved_by) at \(.approved_at)  forecast \(.forecast_high_f)F",
      (.stops[] | "  truck #\(.stop)  \(.latitude), \(.longitude)  \(.neighborhood // "")"
                  + (if .override_reason then "  (moved: \(.override_reason))" else "" end)),
      (.wellness_teams[] | "  wellness team \(.team)  tract \(.tract_geo_id // "?")  \(.neighborhood // "")"))'
else
  call GET /api/dispatches/active
  expect 200
fi
