# Sourced by the other scripts: loads .env, resolves project/region/venv.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi
PROJECT="${PROJECT:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${REGION:-${GOOGLE_CLOUD_LOCATION:-us-central1}}"
VENV="${VENV:-$ROOT/.venv}"
PY="$VENV/bin/python"; ADK="$VENV/bin/adk"
[ -n "$PROJECT" ] && [ "$PROJECT" != "your-project-id" ] || { echo "Set GOOGLE_CLOUD_PROJECT in .env (or PROJECT=...)" >&2; exit 1; }
export GOOGLE_CLOUD_PROJECT="$PROJECT" BQ_DATASET="${BQ_DATASET:-a4i_climate}" BQ_LOCATION="${BQ_LOCATION:-US}"
echo ">> project=$PROJECT region=$REGION dataset=$BQ_DATASET"

save_env() {  # key value : upsert into .env (macOS-safe sed)
  touch "$ROOT/.env"
  if grep -q "^$1=" "$ROOT/.env"; then sed -i.bak "s|^$1=.*|$1=$2|" "$ROOT/.env" && rm -f "$ROOT/.env.bak"; else echo "$1=$2" >> "$ROOT/.env"; fi
}
