#!/usr/bin/env bash
# Load the CSV snapshots in data/chicago/sites/ into BigQuery, one table per file, prefixed chi_site_.
# Every table is fully replaced (--replace), so re-running is always safe.
#
#   bash tools/load_chicago_sites_bq.sh                       # uses GOOGLE_CLOUD_PROJECT / BQ_DATASET from env or .env
#   bash tools/load_chicago_sites_bq.sh my-project a4i_climate
#
# Afterwards, e.g.:
#   SELECT site_name, site_category, ST_GEOGPOINT(longitude, latitude) AS geo
#   FROM `PROJECT.DATASET.chi_site_candidate_sites` WHERE is_current_cooling_site;
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a
PROJECT="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
DATASET="${2:-${BQ_DATASET:-a4i_climate}}"
LOCATION="${BQ_LOCATION:-US}"
DIR=data/chicago/sites
[ -n "$PROJECT" ] || { echo "set GOOGLE_CLOUD_PROJECT or pass PROJECT as the first argument" >&2; exit 2; }

bq --location="$LOCATION" mk -f --dataset "$PROJECT:$DATASET" >/dev/null 2>&1 || true
for csv in "$DIR"/*.csv; do
  name="$(basename "$csv" .csv)"
  table="$PROJECT:$DATASET.chi_site_$name"
  echo "loading $csv -> $table"
  bq --location="$LOCATION" load --replace --source_format=CSV --skip_leading_rows=1 \
     --allow_quoted_newlines "$table" "$csv" "$DIR/bq_schemas/$name.json"
done
echo "done. tables: $(ls "$DIR"/*.csv | xargs -n1 basename | sed 's/\.csv$//; s/^/chi_site_/' | tr '\n' ' ')"
