#!/usr/bin/env bash
# Build / evaluate the v2 heat model candidate beside the live model (sql/v2/*.sql; never touches heat_offset_model).
#   bash scripts/run_v2.sh build      # site_context_lst view + heat_offset_trend_only + heat_offset_lst
#   bash scripts/run_v2.sh evaluate   # held-out comparison + edge-cell check
#   bash scripts/run_v2.sh render sql/v2/11_train_lst.sql
# Uses the bq CLI (no ADC). Where ~/.config/gcloud is blocked: CLOUDSDK_CONFIG=$PWD/.gcloud PROJECT=<id> bash ...
set -euo pipefail
. "$(dirname "$0")/_env.sh" >/dev/null
render() { "$PY" -c "
import sys; sys.path.insert(0, '$ROOT/scripts')
from pathlib import Path
from run_sql import load_vars, render
print(render(Path('$1').read_text(), load_vars('$PROJECT', '$BQ_DATASET')))"; }
run() { render "$1" | bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --nouse_legacy_sql --format=pretty; }  # stdin: SQL starts with "--"
case "${1:-}" in
  build)    run "$ROOT/sql/v2/10_site_context_lst.sql"; run "$ROOT/sql/v2/11_train_lst.sql" ;;
  evaluate) run "$ROOT/sql/v2/12_evaluate_lst.sql" ;;
  render)   render "$2" ;;
  *) echo "usage: $0 build|evaluate|render <file>" >&2; exit 2 ;;
esac
