#!/usr/bin/env python3
"""Call every Toolbox tool once against the running server and print what came back (live BigQuery + model).

    make toolbox-local          # terminal 1
    make smoke                  # terminal 2

Run this BEFORE trusting the agent: it is the quickest way to find a SQL or schema error in tools.yaml.
For a deployed (private) Toolbox, the script sends your gcloud identity token.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from heat_dispatch.config import get_settings  # noqa: E402
from heat_dispatch.results import parse_rows  # noqa: E402
from toolbox_core import ToolboxSyncClient  # noqa: E402

CASES = {
    "model_card": {},
    "model_global_importance": {},
    "heat_frequency": {"threshold_f": 95},
    "rank_priority_sites": {"limit": 5},
    "rank_wellness_check_tracts": {"limit": 5},
    "predict_site_heat": {"latitude": 41.7796, "longitude": -87.6444},       # 63rd & Halsted (Englewood)
    "who_lives_near": {"latitude": 41.7796, "longitude": -87.6444},
    "nearest_cooling_facilities": {"latitude": 41.7796, "longitude": -87.6444, "facility_type": "Library", "limit": 3},
    "equity_audit": {"limit": 5},
    "tract_map_layer": {},
    "list_sites": {"category": "Library"},
}


def main() -> int:
    s = get_settings()
    headers = {}
    if not s.toolbox_url.startswith("http://127.0.0.1"):
        tok = subprocess.run(["gcloud", "auth", "print-identity-token"], capture_output=True, text=True, check=True).stdout.strip()
        headers = {"Authorization": f"Bearer {tok}"}
    client = ToolboxSyncClient(s.toolbox_url, client_headers=headers)
    tools = {t.__name__: t for t in client.load_toolset(s.toolbox_toolset)}
    print(f"server {s.toolbox_url}: {len(tools)} tools -> {sorted(tools)}")
    failed = 0
    for name, args in CASES.items():
        if name not in tools:
            print(f"MISSING {name}"); failed += 1; continue
        try:
            rows = parse_rows(tools[name](**args))
            print(f"OK   {name}: {len(rows)} row(s)")
            if rows:
                print("     " + json.dumps(rows[0], default=str)[:400])
            if not rows and name != "nearest_cooling_facilities":
                print("     !! zero rows: check the tables behind this tool"); failed += 1
        except Exception as exc:
            print(f"FAIL {name}: {str(exc)[:500]}"); failed += 1
    print("\nALL OK" if not failed else f"\n{failed} problem(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
