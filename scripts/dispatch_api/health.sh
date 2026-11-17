#!/usr/bin/env bash
# GET /health : is the server up? (not /healthz: Cloud Run reserves paths ending in "z")
#   bash scripts/dispatch_api/health.sh
. "$(dirname "$0")/_common.sh"
call GET /health
expect 200
