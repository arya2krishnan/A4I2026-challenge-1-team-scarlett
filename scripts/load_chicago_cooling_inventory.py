#!/usr/bin/env python3
"""Save current Chicago cooling inventory, with unknown readiness explicitly null.

Default writes data/enrichment/facilities; --load uses cooling_inventory_snapshot.
It does not change cooling_facilities. Text hours are preserved without inferring
event-specific opening, staffing, capacity, working AC or accessibility.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

from load_chicago_facilities import SCHEMA as BASE_SCHEMA
from load_chicago_facilities import URL, fetch, normalize

TABLE = "cooling_inventory_snapshot"
TERMS_URL = "https://www.chicago.gov/city/en/narr/foia/data_disclaimer.html"
METADATA_URL = "https://data.cityofchicago.org/api/views/msrk-w9ih.json"
SCHEMA = BASE_SCHEMA + [("open_for_event", "BOOL"), ("available_capacity", "INT64"),
                       ("working_ac_confirmed", "BOOL"), ("staffing_confirmed", "BOOL"),
                       ("wheelchair_accessible_confirmed", "BOOL"), ("readiness_verified_at", "TIMESTAMP")]


def normalize_inventory(records: list[dict], retrieved_at: str) -> list[dict]:
    return [{**row, "open_for_event": None, "available_capacity": None,
             "working_ac_confirmed": None, "staffing_confirmed": None,
             "wheelchair_accessible_confirmed": None, "readiness_verified_at": None}
            for row in normalize(records, retrieved_at)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, default=Path("data/enrichment/facilities"))
    parser.add_argument("--load", action="store_true")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument("--dataset", default=os.environ.get("BQ_DATASET", "a4i_climate"))
    parser.add_argument("--location", default=os.environ.get("BQ_LOCATION", "US"))
    args = parser.parse_args()
    if args.load and not args.project:
        parser.error("--load requires --project or GOOGLE_CLOUD_PROJECT")
    retrieved_at = dt.datetime.now(dt.timezone.utc).isoformat()
    raw = fetch()
    req = urllib.request.Request(METADATA_URL, headers={"User-Agent": "heat-dispatch-agent/1.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        metadata = json.load(response)
    rows = normalize_inventory(raw, retrieved_at)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "source.json").write_text(json.dumps(raw) + "\n")
    (args.output_dir / "source_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    with (args.output_dir / f"{TABLE}.jsonl").open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, allow_nan=False) + "\n")
    manifest = {"source": URL, "terms_url": TERMS_URL, "retrieved_at": retrieved_at,
                "metadata_source": METADATA_URL,
                "source_time_period": metadata.get("metadata", {}).get("custom_fields", {}).get("Metadata", {}).get("Time Period"),
                "source_rows_updated_at": (dt.datetime.fromtimestamp(metadata["rowsUpdatedAt"], dt.timezone.utc).isoformat()
                                           if metadata.get("rowsUpdatedAt") else None),
                "source_license": metadata.get("license", {}).get("name"),
                "source_rows": len(raw), "normalized_rows": len(rows), "dropped_rows": len(raw) - len(rows),
                "facility_types": dict(Counter(r["facility_type"] for r in rows)),
                "listed_indoor_sites": sum(r["is_indoor"] for r in rows),
                "coverage": "City of Chicago Cooling Centers inventory with usable Chicago-area coordinates",
                "limitations": ["Hours are source free text; no holiday/event opening inferred",
                                "Indoor designation is inventory screening, not verification of working AC",
                                "Capacity, staffing, accessible entrance and event readiness require operator confirmation",
                                "Chicago portal terms apply; data provided without guarantee of accuracy"]}
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output_dir": str(args.output_dir), **manifest}, indent=2))
    if args.load:
        from google.cloud.bigquery.client import Client
        from google.cloud.bigquery.job.load import LoadJobConfig
        from google.cloud.bigquery.schema import SchemaField

        client = Client(project=args.project, location=args.location)
        target = f"{args.project}.{args.dataset}.{TABLE}"
        config = LoadJobConfig(schema=[SchemaField(n, t) for n, t in SCHEMA],
                                       write_disposition="WRITE_TRUNCATE")
        client.load_table_from_json(rows, target, job_config=config).result()
        print(f"loaded {len(rows):,} rows into {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
