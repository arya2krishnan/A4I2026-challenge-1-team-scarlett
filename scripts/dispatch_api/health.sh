#!/usr/bin/env bash
# GET /healthz : is the server up?
#   bash scripts/dispatch_api/health.sh
. "$(dirname "$0")/_common.sh"
call GET /healthz
expect 200
