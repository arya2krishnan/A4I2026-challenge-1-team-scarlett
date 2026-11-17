#!/usr/bin/env bash
# One command from an empty GCP project to everything deployed. Idempotent: safe to re-run, or resume with --from.
#
#   bash scripts/setup_all.sh                 # all steps, asks once before touching GCP
#   bash scripts/setup_all.sh --yes           # no prompt
#   bash scripts/setup_all.sh --from model    # resume at a step
#   bash scripts/setup_all.sh --only api      # one step
#   bash scripts/setup_all.sh --list          # show the steps
#
# Steps (each wraps an existing script/make target; docs/RUNBOOK.md says what proves each one worked):
#   venv     .venv (Python 3.11) + requirements-dev.txt, .env from .env.example
#   auth     gcloud project + application-default credentials (+ quota project)
#   gcp      APIs, service accounts, roles                  (scripts/setup_gcp.sh, needs project admin)
#   data     3 source tables from the GCS snapshot, City of Chicago facilities, high schools, boundaries
#   osm      OpenStreetMap land cover -> osm_chicago        (~3 GB scanned; skipped if the table exists, FORCE_OSM=1 redoes)
#   model    sql/01..06: grid, vulnerability, site context, TRAIN BQML, evaluate, validate
#   tools    run every Toolbox tool's SQL against BigQuery (catches a broken tool before deploying it)
#   toolbox  MCP Toolbox -> Cloud Run (private, min-instances=1)
#   agent    agent -> Agent Runtime
#   client   Streamlit client -> Cloud Run
#   api      dispatch approval API -> Cloud Run + Firestore + signing key in Secret Manager
#   smoke    end-to-end test of the deployed dispatch API
#
# Written for macOS bash 3.2 as well as Cloud Shell (it does not call scripts/load.sh, which needs bash 4).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STEPS="venv auth gcp data osm model tools toolbox agent client api smoke"
SNAPSHOT="gs://class-demo/a4i-2026/challenge-1-walkability/chicago"
SOURCE_TABLES="heat_observations station_daily_temps tract_demographics"

bold() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

FROM=""; ONLY=""; YES=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="${2:-}"; shift 2 ;;
    --only) ONLY="${2:-}"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --list) echo "$STEPS" | tr ' ' '\n'; exit 0 ;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done
for s in $FROM $ONLY; do
  case " $STEPS " in *" $s "*) ;; *) die "unknown step '$s'. Steps: $STEPS" ;; esac
done

# Which steps run: all, from FROM onwards, or just ONLY.
RUN=""; started=""
[ -z "$FROM" ] && started=1
for s in $STEPS; do
  [ "$s" = "$FROM" ] && started=1
  if [ -n "$ONLY" ]; then [ "$s" = "$ONLY" ] && RUN="$RUN $s"; elif [ -n "$started" ]; then RUN="$RUN $s"; fi
done
wants() { case " $RUN " in *" $1 "*) return 0 ;; esac; return 1; }

# ---------------------------------------------------------------- preflight (no GCP changes)
for c in gcloud bq openssl; do command -v "$c" >/dev/null 2>&1 || die "'$c' not found. Install the Google Cloud SDK (or use Cloud Shell)."; done
[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example."; }
set -a; . ./.env; set +a
PROJECT="${GOOGLE_CLOUD_PROJECT:-}"
[ -n "$PROJECT" ] && [ "$PROJECT" != "your-project-id" ] || die "Set GOOGLE_CLOUD_PROJECT in .env, then re-run."
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
DATASET="${BQ_DATASET:-a4i_climate}"; BQ_LOC="${BQ_LOCATION:-US}"
PY="$ROOT/.venv/bin/python"

bold "Plan"
echo "  project : $PROJECT"
echo "  region  : $REGION   (BigQuery: $DATASET in $BQ_LOC)"
echo "  steps   :$RUN"
echo "  This creates billable resources (Cloud Run x3 with one warm Toolbox instance, Agent Runtime,"
echo "  Firestore, Secret Manager, BigQuery storage + a ~3 GB OSM scan)."
if [ -z "$YES" ]; then
  printf '  Continue? [y/N] '; read -r ans
  case "$ans" in y|Y|yes|YES) ;; *) echo "Nothing changed."; exit 0 ;; esac
fi

# ---------------------------------------------------------------- steps
step_venv() {
  if [ ! -x "$PY" ]; then
    command -v python3.11 >/dev/null 2>&1 || die "python3.11 not found (brew install python@3.11)."
    python3.11 -m venv .venv
  fi
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements-dev.txt
  "$PY" -m pytest tests -q
}

step_auth() {
  gcloud config set project "$PROJECT" >/dev/null
  gcloud auth print-access-token >/dev/null 2>&1 || gcloud auth login
  if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
    gcloud auth application-default login
  fi
  gcloud auth application-default set-quota-project "$PROJECT" >/dev/null 2>&1 || \
    echo "  (could not set the ADC quota project; fine unless BigQuery calls fail with a quota-project error)"
  "$PY" scripts/check_models.py
}

step_gcp() {
  bash scripts/setup_gcp.sh
  gcloud services enable --project "$PROJECT" firestore.googleapis.com
}

step_data() {
  if ! bq --project_id="$PROJECT" show --dataset --format=none "$PROJECT:$DATASET" >/dev/null 2>&1; then
    bq --project_id="$PROJECT" --location="$BQ_LOC" mk --dataset "$PROJECT:$DATASET"
  fi
  for t in $SOURCE_TABLES; do
    echo "  loading $t"
    bq --project_id="$PROJECT" --location="$BQ_LOC" load --source_format=PARQUET --replace \
      "$DATASET.$t" "$SNAPSHOT/$t/*.parquet" >/dev/null
  done
  "$PY" scripts/load_chicago_facilities.py
  "$PY" scripts/load_chicago_high_schools.py   # after facilities: it appends High School rows to cooling_facilities
  "$PY" scripts/load_chicago_boundaries.py
  bq --project_id="$PROJECT" --location="$BQ_LOC" query --use_legacy_sql=false --format=pretty \
    "SELECT COUNT(*) AS street_readings, ROUND(MAX(temp_f) - MIN(temp_f), 1) AS spread_f
     FROM \`$PROJECT.$DATASET.heat_observations\`"
}

step_osm() {
  if [ -z "${FORCE_OSM:-}" ] && bq --project_id="$PROJECT" show --format=none "$PROJECT:$DATASET.osm_chicago" >/dev/null 2>&1; then
    echo "  osm_chicago already exists: skipping the ~3 GB scan (FORCE_OSM=1 to rebuild)"; return
  fi
  "$PY" scripts/run_sql.py 00
}

step_model()   { "$PY" scripts/run_sql.py 01 02 03 04 05 06; }
step_tools()   { "$PY" scripts/check_tool_sql.py; }
step_toolbox() { bash scripts/deploy_toolbox.sh; }
step_agent()   { bash scripts/deploy_agent.sh; }
step_client()  { bash scripts/deploy_client.sh; }
step_api()     { bash scripts/deploy_api.sh; }
step_smoke()   { set -a; . ./.env; set +a; "$PY" scripts/smoke_dispatch_api.py; }

# Not `if ! step_x`: bash disables set -e inside a function called from a condition, hiding mid-step failures.
CURRENT=""
on_exit() {
  rc=$?
  if [ $rc -ne 0 ] && [ -n "$CURRENT" ]; then
    printf '\n\033[1mERROR:\033[0m step %s failed (exit %s). Fix it, then resume with:\n  bash scripts/setup_all.sh --from %s\n' \
      "$CURRENT" "$rc" "$CURRENT" >&2
  fi
}
trap on_exit EXIT
for s in $RUN; do
  CURRENT="$s"; bold "$s"
  # Later steps read values earlier ones wrote to .env (TOOLBOX_URL, AGENT_RESOURCE_NAME, ...).
  set -a; . ./.env; set +a
  "step_$s"
done
CURRENT=""

set -a; . ./.env; set +a
bold "Done"
echo "  Toolbox : ${TOOLBOX_URL:-}"
echo "  Agent   : ${AGENT_RESOURCE_NAME:-}"
echo "  API     : ${DISPATCH_API_URL:-}"
echo "  Client  : gcloud run services proxy ${CLIENT_SERVICE_NAME:-heat-dispatch-client} --region $REGION --project $PROJECT"
