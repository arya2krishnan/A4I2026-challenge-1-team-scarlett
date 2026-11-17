#!/usr/bin/env python3
"""Load the City of Chicago "Cooling Centers" dataset into BigQuery as `cooling_facilities`.

Source : https://data.cityofchicago.org/Health-Human-Services/Cooling-Centers/msrk-w9ih  (Socrata id msrk-w9ih)
Why    : the README says to bring a dataset nobody else has. A Today-track dispatcher needs to know
         where people can already get indoors (79 libraries, senior centers, colleges, ...), so the
         agent can find hot, vulnerable places that are FAR from any of them.
Terms  : City of Chicago data portal terms of use (the dataset's licence field reads "See Terms of Use").
         The snapshot is a point-in-time copy: hours change and holiday closures are listed in the text.

    python scripts/load_chicago_facilities.py            # load into BigQuery
    python scripts/load_chicago_facilities.py --dry-run  # fetch + normalise + print, load nothing
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from collections import Counter

DATASET_ID = "msrk-w9ih"
URL = f"https://data.cityofchicago.org/resource/{DATASET_ID}.json?$limit=5000"
# Outdoors, or not guaranteed air-conditioned: they do not count as "somewhere indoors to cool down".
NOT_INDOOR = {"Park District Spray Feature", "Park District Facility"}

SCHEMA = [
    ("facility_type", "STRING"), ("site_name", "STRING"), ("address", "STRING"), ("zip", "STRING"),
    ("phone", "STRING"), ("hours_of_operation", "STRING"), ("latitude", "FLOAT64"),
    ("longitude", "FLOAT64"), ("is_indoor", "BOOL"), ("source", "STRING"), ("retrieved_at", "TIMESTAMP"),
]


def fetch(url: str = URL) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "heat-dispatch-agent/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def normalize(records: list[dict], retrieved_at: str | None = None) -> list[dict]:
    """Socrata rows -> flat rows. Drops rows without a usable point (counted, never silent)."""
    retrieved_at = retrieved_at or dt.datetime.now(dt.timezone.utc).isoformat()
    out = []
    for r in records:
        loc = r.get("location") or {}
        coords = loc.get("coordinates")
        try:
            lon, lat = float(coords[0]), float(coords[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (41.5 < lat < 42.2 and -88.1 < lon < -87.4):   # inside the Chicago area, else a bad geocode
            continue
        ftype = (r.get("site_type") or "").strip()
        out.append({
            "facility_type": ftype,
            "site_name": (r.get("site_name") or "").strip(),
            "address": (r.get("address") or "").strip(),
            "zip": (r.get("zip") or "").strip(),
            "phone": (r.get("phone") or "").strip(),
            "hours_of_operation": (r.get("hours_of_operation") or "").strip(),
            "latitude": lat, "longitude": lon,
            "is_indoor": ftype not in NOT_INDOOR,
            "source": f"data.cityofchicago.org/{DATASET_ID}",
            "retrieved_at": retrieved_at,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    ap.add_argument("--dataset", default=os.environ.get("BQ_DATASET", "a4i_climate"))
    ap.add_argument("--location", default=os.environ.get("BQ_LOCATION", "US"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw = fetch()
    rows = normalize(raw)
    print(f"fetched {len(raw)} rows, kept {len(rows)} with a usable Chicago location")
    for t, n in Counter(r["facility_type"] for r in rows).most_common():
        print(f"  {t:32s} {n}")
    print(f"  indoor cooling sites: {sum(r['is_indoor'] for r in rows)}")
    if args.dry_run:
        return 0
    if not args.project:
        print("set GOOGLE_CLOUD_PROJECT or pass --project", file=sys.stderr)
        return 2

    from google.cloud import bigquery

    client = bigquery.Client(project=args.project, location=args.location)
    table = f"{args.project}.{args.dataset}.cooling_facilities"
    job = client.load_table_from_json(
        rows, table,
        job_config=bigquery.LoadJobConfig(
            schema=[bigquery.SchemaField(n, t) for n, t in SCHEMA],
            write_disposition="WRITE_TRUNCATE",
        ),
    )
    job.result()
    print(f"loaded {client.get_table(table).num_rows} rows into {table}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
