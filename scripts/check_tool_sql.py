#!/usr/bin/env python3
"""Run every tool's exact SQL in toolbox/tools.yaml against BigQuery with named parameters (what Toolbox does), no Toolbox needed.

    python scripts/check_tool_sql.py           # run all tools with their defaults / sample arguments
    python scripts/check_tool_sql.py --dry-run # BigQuery validation only

Catches SQL, schema and model errors before anything is deployed. `make smoke` later checks the MCP layer on top.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml
from google.cloud import bigquery

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_toolbox import resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = {"latitude": 41.7796, "longitude": -87.6444, "facility_type": "Library"}   # 63rd & Halsted, Englewood
BQ_TYPES = {"integer": "INT64", "float": "FLOAT64", "string": "STRING", "boolean": "BOOL"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    text = resolve((ROOT / "toolbox" / "tools.yaml").read_text(), {**os.environ, "GOOGLE_CLOUD_PROJECT": project})
    client = bigquery.Client(project=project, location=os.environ.get("BQ_LOCATION", "US"))
    bad = 0
    for d in yaml.safe_load_all(text):
        if d.get("kind") != "tool":
            continue
        params = []
        for p in d["parameters"]:
            val = SAMPLE.get(p["name"], p.get("default"))
            params.append(bigquery.ScalarQueryParameter(p["name"], BQ_TYPES[p["type"]], val))
        cfg = bigquery.QueryJobConfig(query_parameters=params, dry_run=args.dry_run, use_query_cache=False)
        try:
            job = client.query(d["statement"], job_config=cfg)
            rows = [] if args.dry_run else [dict(r.items()) for r in job.result()]
            print(f"OK   {d['name']}: {'dry run' if args.dry_run else str(len(rows)) + ' row(s)'}")
            if rows:
                print("     " + json.dumps(rows[0], default=str)[:600])
            if not args.dry_run and not rows:
                print("     !! zero rows"); bad += 1
        except Exception as exc:
            print(f"FAIL {d['name']}: {str(exc)[:700]}"); bad += 1
    print("\nALL OK" if not bad else f"\n{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
