#!/usr/bin/env python3
"""Render and run the data/model SQL in sql/ against BigQuery.

    python scripts/run_sql.py                      # every NN_*.sql in order (01..06)
    python scripts/run_sql.py 01 02                # just those steps
    python scripts/run_sql.py --render 04          # print the rendered SQL, touch nothing
    python scripts/run_sql.py --dry-run            # ask BigQuery to validate each statement (no cost, no writes)

{{NAME}} tokens come from sql/chicago.json plus PROJECT / DATASET (and ACS_TABLE, discovered).
Steps 01-03 (re)build tables and 04 trains the model, so this is safe to re-run end to end.
Run `bash scripts/load.sh chicago` first (the three source tables) and
`python scripts/load_chicago_facilities.py` before step 03.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql"
TOKEN = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def load_vars(project: str, dataset: str, extra: dict | None = None) -> dict:
    cfg = {k: v for k, v in json.loads((SQL_DIR / "chicago.json").read_text()).items() if not k.startswith("_")}
    cfg.update({"PROJECT": project, "DATASET": dataset})
    cfg.update(extra or {})
    return cfg


def render(sql: str, variables: dict) -> str:
    """Replace {{TOKENS}}; an unknown token is an error, never a silent blank."""
    missing = sorted({m for m in TOKEN.findall(sql) if m not in variables})
    if missing:
        raise KeyError(f"unresolved SQL variables: {', '.join(missing)}")
    return TOKEN.sub(lambda m: str(variables[m.group(1)]), sql)


def sql_files(selected: list[str]) -> list[Path]:
    files = sorted(SQL_DIR.glob("[0-9][0-9]_*.sql"))
    if selected:
        files = [f for f in files if any(f.name.startswith(s.zfill(2)) for s in selected)]
    return files


def discover_acs_table(client) -> str:
    """Newest ACS census-tract table, asked of BigQuery rather than hard-coded (the notebook does the same)."""
    rows = client.query(
        "SELECT table_name FROM `bigquery-public-data.census_bureau_acs.INFORMATION_SCHEMA.TABLES` "
        "WHERE table_name LIKE 'censustract%' ORDER BY table_name DESC LIMIT 1"
    ).result()
    for r in rows:
        return r.table_name
    raise RuntimeError("no censustract table found in bigquery-public-data.census_bureau_acs")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("steps", nargs="*", help="step prefixes, e.g. 01 04 (default: all)")
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    ap.add_argument("--dataset", default=os.environ.get("BQ_DATASET", "a4i_climate"))
    ap.add_argument("--location", default=os.environ.get("BQ_LOCATION", "US"))
    ap.add_argument("--render", action="store_true", help="print rendered SQL and exit")
    ap.add_argument("--dry-run", action="store_true", help="validate with BigQuery, run nothing")
    args = ap.parse_args()

    files = sql_files(args.steps)
    if not files:
        print("no matching sql files", file=sys.stderr)
        return 2
    if args.render:
        v = load_vars(args.project or "PROJECT", args.dataset, {"ACS_TABLE": "censustract_YYYY_5yr"})
        for f in files:
            print(f"-- ===== {f.name}\n{render(f.read_text(), v)}\n")
        return 0
    if not args.project:
        print("set GOOGLE_CLOUD_PROJECT or pass --project", file=sys.stderr)
        return 2

    from google.cloud import bigquery

    client = bigquery.Client(project=args.project, location=args.location)
    extra = {}
    if any("{{ACS_TABLE}}" in f.read_text() for f in files):
        extra["ACS_TABLE"] = discover_acs_table(client)
        print(f"ACS table: {extra['ACS_TABLE']}")
    variables = load_vars(args.project, args.dataset, extra)

    for f in files:
        sql = render(f.read_text(), variables)
        print(f"\n>> {f.name}{'  (dry run)' if args.dry_run else ''}")
        job = client.query(sql, job_config=bigquery.QueryJobConfig(dry_run=args.dry_run, use_query_cache=False))
        if args.dry_run:
            print(f"   ok, would process {job.total_bytes_processed or 0:,} bytes")
            continue
        rows = list(job.result())
        if rows and f.name[:2] in ("05", "06"):
            for r in rows:
                print("   ", dict(r.items()))
        print(f"   done ({(job.total_bytes_processed or 0) / 1e9:.2f} GB processed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
