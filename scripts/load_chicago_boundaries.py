#!/usr/bin/env python3
"""Load the City of Chicago community-area boundaries (77 named neighbourhoods) into BigQuery as `community_areas`.

Source : https://data.cityofchicago.org/resource/igwz-8jzy  (Boundaries - Community Areas); terms: "See Terms of Use"
Why    : (1) clip the model grid to the CITY (the Heat Watch footprint also covers inner suburbs such as Berwyn and Cicero,
         where a Chicago dispatcher cannot send a truck); (2) give every stop a neighbourhood name a dispatcher recognises.

    python scripts/load_chicago_boundaries.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

URL = "https://data.cityofchicago.org/resource/igwz-8jzy.json?$limit=100"


def fetch() -> list[dict]:
    req = urllib.request.Request(URL, headers={"User-Agent": "heat-dispatch-agent/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def normalize(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        geom = r.get("the_geom")
        if not geom or not r.get("community"):
            continue
        out.append({"community": r["community"].title(), "area_number": int(r.get("area_numbe") or 0),
                    "geojson": json.dumps(geom)})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    ap.add_argument("--dataset", default=os.environ.get("BQ_DATASET", "a4i_climate"))
    ap.add_argument("--location", default=os.environ.get("BQ_LOCATION", "US"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    rows = normalize(fetch())
    print(f"fetched {len(rows)} community areas")
    if len(rows) != 77:
        print("!! expected 77", file=sys.stderr)
    if args.dry_run:
        return 0 if len(rows) == 77 else 1
    from google.cloud import bigquery

    client = bigquery.Client(project=args.project, location=args.location)
    raw = f"{args.project}.{args.dataset}.community_areas_raw"
    client.load_table_from_json(rows, raw, job_config=bigquery.LoadJobConfig(
        schema=[bigquery.SchemaField("community", "STRING"), bigquery.SchemaField("area_number", "INT64"),
                bigquery.SchemaField("geojson", "STRING")], write_disposition="WRITE_TRUNCATE")).result()
    client.query(f"""CREATE OR REPLACE TABLE `{args.project}.{args.dataset}.community_areas` AS
        SELECT community, area_number, ST_GEOGFROMGEOJSON(geojson, make_valid => TRUE) AS geom FROM `{raw}`""").result()
    n = list(client.query(f"SELECT COUNT(*) n, COUNTIF(geom IS NULL) bad FROM `{args.project}.{args.dataset}.community_areas`").result())[0]
    print(f"community_areas: {n.n} rows, {n.bad} null geometries")
    return 0 if n.bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
