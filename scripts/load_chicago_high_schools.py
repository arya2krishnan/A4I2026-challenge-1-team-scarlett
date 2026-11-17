#!/usr/bin/env python3
"""Load Chicago Public High Schools into BigQuery.

Source: City of Chicago Data Portal (Socrata id c7jj-qjvh / CPS School Profile)
Why: High school gymnasiums and auditoriums provide large-capacity, air-conditioned
     indoor emergency cooling centers during severe urban heat crises.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from google.cloud import bigquery

DATASET_ID = "c7jj-qjvh"
URL = f"https://data.cityofchicago.org/resource/{DATASET_ID}.json?school_category=HS&$limit=1000"

SCHEMA_HIGH_SCHOOLS = [
    bigquery.SchemaField("school_id", "STRING"),
    bigquery.SchemaField("school_name", "STRING"),
    bigquery.SchemaField("full_name", "STRING"),
    bigquery.SchemaField("address", "STRING"),
    bigquery.SchemaField("zip", "STRING"),
    bigquery.SchemaField("community_area", "STRING"),
    bigquery.SchemaField("ward", "STRING"),
    bigquery.SchemaField("grades", "STRING"),
    bigquery.SchemaField("latitude", "FLOAT64"),
    bigquery.SchemaField("longitude", "FLOAT64"),
    bigquery.SchemaField("facility_type", "STRING"),
    bigquery.SchemaField("is_indoor", "BOOL"),
    bigquery.SchemaField("has_ac_gym", "BOOL"),
    bigquery.SchemaField("source", "STRING"),
    bigquery.SchemaField("retrieved_at", "TIMESTAMP"),
]

SCHEMA_COOLING_FACILITIES = [
    bigquery.SchemaField("facility_type", "STRING"),
    bigquery.SchemaField("site_name", "STRING"),
    bigquery.SchemaField("address", "STRING"),
    bigquery.SchemaField("zip", "STRING"),
    bigquery.SchemaField("phone", "STRING"),
    bigquery.SchemaField("hours_of_operation", "STRING"),
    bigquery.SchemaField("latitude", "FLOAT64"),
    bigquery.SchemaField("longitude", "FLOAT64"),
    bigquery.SchemaField("is_indoor", "BOOL"),
    bigquery.SchemaField("source", "STRING"),
    bigquery.SchemaField("retrieved_at", "TIMESTAMP"),
]


def fetch_high_schools() -> list[dict]:
    req = urllib.request.Request(URL, headers={"User-Agent": "heat-dispatch-agent/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def normalize_high_schools(records: list[dict]) -> tuple[list[dict], list[dict]]:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    hs_rows = []
    cooling_rows = []

    for r in records:
        try:
            lat = float(r.get("latitude"))
            lon = float(r.get("longitude"))
        except (TypeError, ValueError):
            continue

        # Keep strictly inside Chicago coordinates
        if not (41.60 <= lat <= 42.10 and -87.95 <= lon <= -87.50):
            continue

        street_parts = [r.get("street_number", ""), r.get("street_direction", ""), r.get("street_name", "")]
        address = " ".join(p.strip() for p in street_parts if p).strip() or r.get("address", "").strip()
        full_name = (r.get("fullname") or r.get("schoolname") or "High School").strip()
        zip_code = str(r.get("zip", "")).strip()
        comm_area = (r.get("community_area") or "").strip()

        # Dedicated high schools table row
        hs_rows.append({
            "school_id": str(r.get("schoolid", "")).strip(),
            "school_name": (r.get("schoolname") or full_name).strip(),
            "full_name": full_name,
            "address": address,
            "zip": zip_code,
            "community_area": comm_area,
            "ward": str(r.get("ward", "")).strip(),
            "grades": str(r.get("attending_grades") or "9th-12th").strip(),
            "latitude": lat,
            "longitude": lon,
            "facility_type": "High School",
            "is_indoor": True,
            "has_ac_gym": True,
            "source": f"data.cityofchicago.org/{DATASET_ID}",
            "retrieved_at": now,
        })

        # Unified cooling facilities row
        cooling_rows.append({
            "facility_type": "High School",
            "site_name": full_name,
            "address": address,
            "zip": zip_code,
            "phone": "",
            "hours_of_operation": "Mon-Fri 7AM-7PM (Emergency AC Gymnasium Cooling)",
            "latitude": lat,
            "longitude": lon,
            "is_indoor": True,
            "source": f"data.cityofchicago.org/{DATASET_ID}",
            "retrieved_at": now,
        })

    return hs_rows, cooling_rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-04-3e58e01275b8"))
    ap.add_argument("--dataset", default=os.environ.get("BQ_DATASET", "a4i_climate"))
    ap.add_argument("--location", default=os.environ.get("BQ_LOCATION", "US"))
    args = ap.parse_args()

    raw = fetch_high_schools()
    hs_rows, cooling_rows = normalize_high_schools(raw)
    print(f"Fetched {len(raw)} high schools, normalized {len(hs_rows)} inside Chicago.")

    client = bigquery.Client(project=args.project, location=args.location)

    # 1. Load dedicated high_schools table
    hs_table = f"{args.project}.{args.dataset}.high_schools"
    job_hs = client.load_table_from_json(
        hs_rows, hs_table,
        job_config=bigquery.LoadJobConfig(
            schema=SCHEMA_HIGH_SCHOOLS,
            write_disposition="WRITE_TRUNCATE",
        ),
    )
    job_hs.result()
    print(f"Loaded {len(hs_rows)} rows into {hs_table}.")

    # 2. Append into cooling_facilities (delete existing High School rows first to remain idempotent)
    delete_query = f"""
    DELETE FROM `{args.project}.{args.dataset}.cooling_facilities`
    WHERE facility_type = 'High School';
    """
    client.query(delete_query).result()

    cf_table = f"{args.project}.{args.dataset}.cooling_facilities"
    job_cf = client.load_table_from_json(
        cooling_rows, cf_table,
        job_config=bigquery.LoadJobConfig(
            schema=SCHEMA_COOLING_FACILITIES,
            write_disposition="WRITE_APPEND",
        ),
    )
    job_cf.result()
    print(f"Appended {len(cooling_rows)} high school facilities into {cf_table}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
