#!/usr/bin/env bash
# Build a4i_climate.cell_land_cover (NLCD 2021 imperviousness + tree canopy per grid cell) via BigQuery ST_REGIONSTATS.
#   bash scripts/enrich_land_cover.sh            # render sql/enrich_land_cover.sql and run it with the bq CLI
#   bash scripts/enrich_land_cover.sh --render   # print the rendered SQL only
# Needs grid_cells (sql/01) and the Earth Engine API enabled on the project. Uses `bq` (no ADC needed);
# on machines where ~/.config/gcloud is blocked, run with CLOUDSDK_CONFIG=$PWD/.gcloud.
set -euo pipefail
. "$(dirname "$0")/_env.sh"
SQL="$("$PY" -c "
import sys; sys.path.insert(0, '$ROOT/scripts')
from run_sql import load_vars, render, SQL_DIR
print(render((SQL_DIR / 'enrich_land_cover.sql').read_text(), load_vars('$PROJECT', '$BQ_DATASET')))
")"
if [ "${1:-}" = "--render" ]; then echo "$SQL"; exit 0; fi
printf '%s\n' "$SQL" | bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --nouse_legacy_sql  # stdin: SQL starts with "--"
bq --project_id="$PROJECT" query --nouse_legacy_sql --format=pretty \
  "SELECT COUNT(*) AS n, COUNTIF(impervious_pct IS NULL) AS imp_null, COUNTIF(tree_canopy_pct IS NULL) AS tcc_null
   FROM \`$PROJECT.$BQ_DATASET.cell_land_cover\`"
