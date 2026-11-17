#!/usr/bin/env bash
# Run MCP Toolbox locally against your real BigQuery (uses your gcloud ADC). Downloads the pinned binary on first use.
#   make toolbox-local            # serves http://127.0.0.1:5000  (leave it running; use another terminal for the agent)
set -euo pipefail
. "$(dirname "$0")/_env.sh"
VERSION="${TOOLBOX_VERSION:-v1.17.0}"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"; ARCH="$(uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/')"
BIN="$ROOT/.bin/toolbox-$VERSION"
if [ ! -x "$BIN" ]; then
  mkdir -p "$ROOT/.bin"
  echo ">> downloading toolbox $VERSION ($OS/$ARCH)"
  curl -fsSL -o "$BIN" "https://storage.googleapis.com/mcp-toolbox-for-databases/$VERSION/$OS/$ARCH/toolbox"
  chmod +x "$BIN"
fi
"$PY" "$ROOT/scripts/render_toolbox.py" --out "$ROOT/toolbox/tools.rendered.yaml"
echo ">> toolbox $VERSION on 127.0.0.1:5000  (tools: toolbox/tools.rendered.yaml)"
exec "$BIN" --config "$ROOT/toolbox/tools.rendered.yaml" --address 127.0.0.1 --port 5000
