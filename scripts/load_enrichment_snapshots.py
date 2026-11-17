#!/usr/bin/env python3
"""Validate and optionally upload the already acquired enrichment JSONL files.

--dry-run performs local validation without contacting Google Cloud. Destinations
are a fixed list of enrichment table names. No source/model table is a target.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from subprocess import run
from typing import Any

from clip_chicago_vulnerability import BOUNDARY_SCHEMA
from load_chicago_cooling_inventory import SCHEMA as COOLING_SCHEMA
from load_chicago_environment import SCHEMAS as ENVIRONMENT_SCHEMAS
from load_chicago_transit import PROVENANCE, SCHEMAS as TRANSIT_SCHEMAS
from load_chicago_vulnerability import SCHEMA as VULNERABILITY_SCHEMA
from load_chicago_walkability import SCHEMAS as WALKING_SCHEMAS
from load_chicago_weather import DAILY_SCHEMA, HOURLY_SCHEMA

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("vulnerability", "geography", "environment", "weather", "transit", "facilities", "walkability")


def gcloud_credentials() -> Any:
    """Use the active CLI account when saved application credentials differ.

    Tokens stay in memory. Capture CLI output so credentials are never printed
    or passed as command-line arguments. Google auth can refresh through gcloud.
    """
    from google.oauth2.credentials import Credentials

    def refresh(_request: Any, scopes: Any = None) -> tuple[str, dt.datetime]:
        result = run(["gcloud", "auth", "print-access-token", "--quiet"],
                     capture_output=True, text=True)
        if result.returncode or not result.stdout.strip():
            raise RuntimeError("The active gcloud account needs authentication; run gcloud auth login")
        expiry = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(minutes=30)
        return result.stdout.strip(), expiry

    return Credentials(token=None, refresh_handler=refresh,
                       scopes=["https://www.googleapis.com/auth/cloud-platform"])


def snapshot_specs() -> dict[str, list[tuple[str, list[tuple[str, str]], str]]]:
    """Relative file paths, explicit schemas and write dispositions."""
    provenance = [("source", "STRING"), ("retrieved_at", "TIMESTAMP")]
    return {
        "vulnerability": [("vulnerability/tract_social_vulnerability.jsonl", VULNERABILITY_SCHEMA, "WRITE_APPEND")],
        "geography": [("geography/tract_social_vulnerability_chicago.jsonl", VULNERABILITY_SCHEMA, "WRITE_TRUNCATE"),
                      ("geography/tract_boundaries_chicago.jsonl", BOUNDARY_SCHEMA, "WRITE_TRUNCATE")],
        "environment": [(f"environment/{name}.jsonl", schema, "WRITE_APPEND") for name, schema in ENVIRONMENT_SCHEMAS.items()],
        "weather": [("weather/weather_hourly.jsonl", HOURLY_SCHEMA, "WRITE_TRUNCATE"),
                    ("weather/weather_daily.jsonl", DAILY_SCHEMA, "WRITE_TRUNCATE")],
        "transit": [(f"transit/{name}.jsonl", schema + PROVENANCE, "WRITE_TRUNCATE") for name, schema in TRANSIT_SCHEMAS.items()],
        "facilities": [("facilities/cooling_inventory_snapshot.jsonl", COOLING_SCHEMA, "WRITE_TRUNCATE")],
        "walkability": [(f"walkability/{name}.jsonl", schema + provenance, "WRITE_TRUNCATE") for name, schema in WALKING_SCHEMAS.items()],
    }


def validate_snapshot(path: Path, schema: list[tuple[str, str]]) -> tuple[int, str]:
    expected = {name for name, _ in schema}
    count = 0
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for line_number, raw in enumerate(handle, 1):
            digest.update(raw)
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict) or set(row) != expected:
                raise ValueError(f"{path}:{line_number}: fields do not match explicit table schema")
            # Reject JSON NaN/Infinity before submitting a load job.
            json.dumps(row, allow_nan=False)
            count += 1
    if not count:
        raise ValueError(f"{path}: snapshot is empty; acquire a valid snapshot before loading")
    return count, digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".data/enrichment")
    parser.add_argument("--sources", nargs="+", choices=SOURCES, default=list(SOURCES))
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument("--dataset", default=os.environ.get("BQ_DATASET", "a4i_climate"))
    parser.add_argument("--location", default=os.environ.get("BQ_LOCATION", "US"))
    parser.add_argument("--dry-run", action="store_true", help="Validate all selected local files; make no Cloud requests")
    parser.add_argument("--gcloud-auth", action="store_true", help="Use the active gcloud CLI account instead of saved application credentials")
    parser.add_argument("--report-file", type=Path, help="Save completed load job IDs and source hashes after each table")
    args = parser.parse_args()
    if not args.project or not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", args.project):
        parser.error("provide the destination --project (a Google Cloud project ID)")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,1023}", args.dataset):
        parser.error("provide a valid BigQuery --dataset")
    # Validate every file before making any Cloud request or writing any table.
    specs = snapshot_specs()
    prepared = []
    for source in dict.fromkeys(args.sources):
        for relative_path, schema, disposition in specs[source]:
            path = args.data_dir / relative_path
            count, digest = validate_snapshot(path, schema)
            prepared.append((path, schema, disposition, count, digest))
    plan = {"project": args.project, "dataset": args.dataset, "location": args.location,
            "dry_run": args.dry_run, "tables": [
                {"destination": f"{args.project}.{args.dataset}.{path.stem}", "file": str(path),
                 "rows": count, "sha256": digest, "write_disposition": disposition}
                for path, _, disposition, count, digest in prepared]}
    print(json.dumps(plan, indent=2))
    if args.dry_run:
        return 0
    from google.cloud.bigquery.client import Client
    from google.cloud.bigquery.job.load import LoadJobConfig
    from google.cloud.bigquery.schema import SchemaField

    credentials = gcloud_credentials() if args.gcloud_auth else None
    client = Client(project=args.project, location=args.location, credentials=credentials)
    report: dict[str, Any] = {"project": args.project, "dataset": args.dataset, "location": args.location, "tables": []}
    report_path = args.report_file or args.data_dir / "upload-result.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    for path, schema, disposition, count, digest in prepared:
        target = f"{args.project}.{args.dataset}.{path.stem}"
        config = LoadJobConfig(
            schema=[SchemaField(name, kind) for name, kind in schema],
            source_format="NEWLINE_DELIMITED_JSON", write_disposition=disposition,
        )
        with path.open("rb") as handle:
            job = client.load_table_from_file(handle, target, job_config=config)
            job.result()
        report["tables"].append({"destination": target, "job_id": job.job_id,
                                 "rows_loaded": count, "sha256": digest,
                                 "completed_at": dt.datetime.now(dt.timezone.utc).isoformat()})
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Loaded {count:,} rows into {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
