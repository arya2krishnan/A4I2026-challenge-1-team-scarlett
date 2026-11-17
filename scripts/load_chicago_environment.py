#!/usr/bin/env python3
"""Acquire Chicago tract tree canopy (CMAP/Ecopia 2023) and ACS 2024 housing burden.

Requires the local Chicago tract set from clip_chicago_vulnerability.py. Saves real source
subsets, metadata, normalized JSONL and provenance. Default is local acquisition;
--load optionally appends new BigQuery tables. CMAP's public source specifies no
redistribution license; the manifest records this uncertainty explicitly.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from load_chicago_vulnerability import aggregate, number, ratio

ROOT = Path(__file__).resolve().parents[1]
CANOPY_ITEM_URL = "https://www.arcgis.com/sharing/rest/content/items/2144b38119a04066b33d710048362f91?f=json"
CANOPY_LAYER = "https://services5.arcgis.com/LcMXE3TFhi1BSaCY/arcgis/rest/services/Heat_Vulnerability_Index/FeatureServer/0"
CANOPY_METHOD_URL = "https://cmap.illinois.gov/wp-content/uploads/dlm_uploads/Heat-vulnerability-index-methodology-report.pdf"
CANOPY_FIELDS = ["geoid_tract", "county_fips", "forest"]
ACS_YEAR = 2024
HOUSING_TABLE = "B25070"
HOUSING_URL = ("https://www2.census.gov/programs-surveys/acs/summary_file/2024/"
               "table-based-SF/data/5YRData/acsdt5y2024-b25070.dat")
HOUSING_METADATA_URL = "https://api.census.gov/data/2024/acs/acs5/groups/B25070.json"
HOUSING_COUNT_FIELDS = ["rent_paying_units", "computed_rent_burden_units", "rent_burden_30_plus_units",
                        "rent_burden_50_plus_units", "rent_burden_not_computed_units"]
CANOPY_SCHEMA = [
    ("geo_id", "STRING"), ("tree_canopy_fraction", "FLOAT64"), ("tree_canopy_percent", "FLOAT64"),
    ("canopy_imagery_year", "INTEGER"), ("publication_year", "INTEGER"),
    ("geographic_scope", "STRING"), ("source", "STRING"), ("retrieved_at", "TIMESTAMP"),
    ("reuse_terms_status", "STRING"),
]
HOUSING_SCHEMA = [
    ("geo_id", "STRING"), ("acs_year", "INTEGER"), ("estimate_period", "STRING"),
    ("geographic_scope", "STRING"), ("source", "STRING"), ("retrieved_at", "TIMESTAMP"),
    *[(field, "FLOAT64") for name in HOUSING_COUNT_FIELDS for field in (name, f"{name}_moe")],
    ("rent_burden_30_plus_rate", "FLOAT64"), ("rent_burden_50_plus_rate", "FLOAT64"),
    ("rent_burden_not_computed_rate", "FLOAT64"),
]
SCHEMAS = {"tract_tree_canopy": CANOPY_SCHEMA, "tract_housing_burden": HOUSING_SCHEMA}


def request(url: str) -> Any:
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "heat-dispatch-agent/1.0"}), timeout=90)


def fetch_json(url: str) -> Any:
    with request(url) as response:
        result = json.load(response)
    if isinstance(result, dict) and result.get("error"):
        raise ValueError(f"Source query failed: {result['error']}")
    return result


def chicago_tract_ids(path: Path) -> set[str]:
    if not path.exists():
        raise ValueError("Chicago tract boundaries missing: run scripts/clip_chicago_vulnerability.py first")
    ids = {json.loads(line)["geo_id"] for line in path.read_text().splitlines() if line.strip()}
    if not ids or any(len(geo_id) != 11 or not geo_id.startswith("17031") for geo_id in ids):
        raise ValueError("Expected Chicago-overlapping Cook County tract IDs")
    return ids


def fetch_canopy() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    item = fetch_json(CANOPY_ITEM_URL)
    metadata = fetch_json(f"{CANOPY_LAYER}?f=json")
    available = {field["name"] for field in metadata["fields"]}
    if not set(CANOPY_FIELDS) <= available:
        raise ValueError("CMAP canopy source fields changed")
    alias = next(field["alias"] for field in metadata["fields"] if field["name"] == "forest")
    if "tree canopy" not in alias.lower():
        raise ValueError("CMAP forest field is no longer described as tree canopy")
    params: dict[str, Any] = {"f": "json", "where": "county_fips='17031'", "outFields": ",".join(CANOPY_FIELDS),
                              "returnGeometry": "false", "returnCountOnly": "true"}
    count_url = f"{CANOPY_LAYER}/query?{urlencode(params)}"
    expected_count = fetch_json(count_url)["count"]
    params.pop("returnCountOnly")
    params.update({"resultRecordCount": 1000, "orderByFields": "geoid_tract ASC"})
    features = []
    query_urls = [count_url]
    offset = 0
    while offset < expected_count:
        params["resultOffset"] = offset
        query_url = f"{CANOPY_LAYER}/query?{urlencode(params)}"
        query_urls.append(query_url)
        page = fetch_json(query_url)
        batch = page.get("features", [])
        if not batch:
            raise ValueError("CMAP canopy response was truncated")
        features.extend(batch)
        offset += len(batch)
    if len(features) != expected_count:
        raise ValueError("CMAP canopy count changed during retrieval")
    return {"features": features, "count": expected_count, "query_params": params,
            "query_urls": query_urls}, metadata, item


def normalize_canopy(raw: dict[str, Any], ids: set[str], retrieved_at: str) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for feature in raw["features"]:
        attributes = feature["attributes"]
        geo_id = str(attributes["geoid_tract"])
        if geo_id in seen:
            raise ValueError(f"Duplicate canopy tract {geo_id}")
        seen.add(geo_id)
        if geo_id not in ids:
            continue
        if attributes["county_fips"] != "17031":
            raise ValueError(f"Unexpected canopy county for {geo_id}")
        canopy = number(attributes.get("forest"))
        if canopy is not None and canopy > 1:
            raise ValueError("CMAP forest source unit changed; expected a fraction in [0,1]")
        rows.append({
            "geo_id": geo_id, "tree_canopy_fraction": canopy,
            "tree_canopy_percent": canopy * 100 if canopy is not None else None,
            "canopy_imagery_year": 2023, "publication_year": 2026,
            "geographic_scope": "Whole Cook County census tract intersecting Census Chicago city boundary",
            "source": CANOPY_LAYER, "retrieved_at": retrieved_at,
            "reuse_terms_status": "Public CMAP service; redistribution license unspecified in source metadata",
        })
    if not rows:
        raise ValueError("No Chicago canopy tracts matched")
    return sorted(rows, key=lambda row: row["geo_id"])


def verify_housing_metadata(metadata: dict[str, Any]) -> None:
    variables = metadata["variables"]
    expected_labels = {7: "!!30.0 to 34.9 percent", 8: "!!35.0 to 39.9 percent",
                       9: "!!40.0 to 49.9 percent", 10: "!!50.0 percent or more", 11: "!!Not computed"}
    for component in range(1, 12):
        for suffix in ("E", "M"):
            if f"B25070_{component:03d}{suffix}" not in variables:
                raise ValueError("ACS B25070 fields changed")
    for component, label in expected_labels.items():
        if not variables[f"B25070_{component:03d}E"]["label"].endswith(label):
            raise ValueError("ACS B25070 rent burden category definitions changed")


def fetch_housing() -> tuple[dict[str, dict[str, str]], dict[str, Any], dict[str, Any]]:
    metadata = fetch_json(HOUSING_METADATA_URL)
    verify_housing_metadata(metadata)
    digest = hashlib.sha256()
    byte_count = 0
    rows: dict[str, dict[str, str]] = {}
    with request(HOUSING_URL) as response:
        first = response.readline()
        digest.update(first)
        byte_count += len(first)
        columns = first.decode("utf-8-sig").rstrip("\r\n").split("|")
        expected = ["GEO_ID", *[f"B25070_{suffix}{component:03d}"
                                 for component in range(1, 12) for suffix in ("E", "M")]]
        if not set(expected) <= set(columns) or columns[0] != "GEO_ID":
            raise ValueError("ACS B25070 summary-file columns changed")
        for line in response:
            digest.update(line)
            byte_count += len(line)
            if not line.startswith(b"1400000US17031"):
                continue
            values = line.decode("utf-8").rstrip("\r\n").split("|")
            if len(values) != len(columns):
                raise ValueError("Malformed ACS B25070 summary row")
            record = dict(zip(columns, values))
            geo_id = record.pop("GEO_ID").removeprefix("1400000US")
            if len(geo_id) != 11 or geo_id in rows:
                raise ValueError("Invalid or duplicate housing tract")
            rows[geo_id] = record
    if not rows:
        raise ValueError("No Cook County housing records found")
    return rows, metadata, {"url": HOUSING_URL, "sha256": digest.hexdigest(),
                            "downloaded_bytes": byte_count, "retained_tracts": len(rows)}


def normalize_housing(raw: dict[str, dict[str, str]], ids: set[str], retrieved_at: str) -> list[dict[str, Any]]:
    missing = ids - set(raw)
    if missing:
        raise ValueError(f"ACS housing source lacks {len(missing)} Chicago tracts")
    definitions = {"rent_paying_units": [1], "computed_rent_burden_units": list(range(2, 11)),
                   "rent_burden_30_plus_units": [7, 8, 9, 10], "rent_burden_50_plus_units": [10],
                   "rent_burden_not_computed_units": [11]}
    rows = []
    for geo_id in sorted(ids):
        row: dict[str, Any] = {
            "geo_id": geo_id, "acs_year": ACS_YEAR, "estimate_period": "2020-2024",
            "geographic_scope": "Whole Cook County census tract intersecting Census Chicago city boundary",
            "source": HOUSING_URL, "retrieved_at": retrieved_at,
        }
        for name, components in definitions.items():
            row[name] = aggregate(raw[geo_id], HOUSING_TABLE, components, "E")
            row[f"{name}_moe"] = aggregate(raw[geo_id], HOUSING_TABLE, components, "M")
        row["rent_burden_30_plus_rate"] = ratio(row["rent_burden_30_plus_units"], row["computed_rent_burden_units"])
        row["rent_burden_50_plus_rate"] = ratio(row["rent_burden_50_plus_units"], row["computed_rent_burden_units"])
        row["rent_burden_not_computed_rate"] = ratio(row["rent_burden_not_computed_units"], row["rent_paying_units"])
        rows.append(row)
    return rows


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def save_rows(output_dir: Path, table: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    path = output_dir / f"{table}.jsonl"
    path.write_text("".join(json.dumps(row, allow_nan=False) + "\n" for row in rows))
    return {"rows": len(rows), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "null_counts": {field: sum(row[field] is None for row in rows) for field, _ in SCHEMAS[table]}}


def load_bigquery(table: str, rows: list[dict[str, Any]], project: str, dataset: str, location: str) -> str:
    from google.cloud.bigquery.client import Client
    from google.cloud.bigquery.job.load import LoadJobConfig
    from google.cloud.bigquery.schema import SchemaField

    if not project:
        raise ValueError("--load requires --project or GOOGLE_CLOUD_PROJECT")
    target = f"{project}.{dataset}.{table}"
    client = Client(project=project, location=location)
    client.load_table_from_json(rows, target, job_config=LoadJobConfig(
        schema=[SchemaField(name, kind) for name, kind in SCHEMAS[table]],
        write_disposition="WRITE_APPEND",
    )).result()
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".data/enrichment/environment")
    parser.add_argument("--tracts", type=Path, default=ROOT / ".data/enrichment/geography/tract_boundaries_chicago.jsonl")
    parser.add_argument("--from-cache", action="store_true")
    parser.add_argument("--load", action="store_true")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument("--dataset", default=os.environ.get("BQ_DATASET", "a4i_climate"))
    parser.add_argument("--location", default=os.environ.get("BQ_LOCATION", "US"))
    args = parser.parse_args()
    ids = chicago_tract_ids(args.tracts)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.from_cache:
        manifest = json.loads((output_dir / "manifest.json").read_text())
        if manifest["chicago_tract_input_sha256"] != hashlib.sha256(args.tracts.read_bytes()).hexdigest():
            raise ValueError("Chicago tract boundary input changed; acquire a fresh environment snapshot")
        canopy = json.loads((output_dir / "canopy_raw.json").read_text())
        housing = json.loads((output_dir / "housing_raw.json").read_text())
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            canopy_future = pool.submit(fetch_canopy)
            housing_future = pool.submit(fetch_housing)
            canopy, canopy_metadata, canopy_item = canopy_future.result()
            housing, housing_metadata, housing_provenance = housing_future.result()
        with request(CANOPY_METHOD_URL) as response:
            method_pdf = response.read()
        (output_dir / "cmap_hvi_methodology.pdf").write_bytes(method_pdf)
        write_json(output_dir / "canopy_raw.json", canopy)
        write_json(output_dir / "canopy_layer_metadata.json", canopy_metadata)
        write_json(output_dir / "canopy_item_metadata.json", canopy_item)
        write_json(output_dir / "housing_raw.json", housing)
        write_json(output_dir / "housing_metadata.json", housing_metadata)
        retrieved_at = dt.datetime.now(dt.timezone.utc).isoformat()
        manifest = {
            "retrieved_at": retrieved_at, "chicago_tract_input": str(args.tracts),
            "chicago_tracts": len(ids), "chicago_tract_input_sha256": hashlib.sha256(args.tracts.read_bytes()).hexdigest(),
            "geographic_policy": "Select Chicago-overlapping Cook County tracts from saved Census city intersection; retain whole-tract values",
            "canopy_source": {"url": CANOPY_LAYER, "item_url": CANOPY_ITEM_URL,
                              "query_params": canopy["query_params"], "county_tracts": canopy["count"],
                              "query_urls": canopy["query_urls"],
                              "canopy_imagery_year": 2023, "publication_year": 2026,
                              "source_unit": "forest values are area fractions in [0,1]; percentage = fraction * 100",
                              "source_field_alias": "Percentage of census tract area with tree canopy",
                              "methodology_url": CANOPY_METHOD_URL,
                              "methodology_sha256": hashlib.sha256(method_pdf).hexdigest(),
                              "license_info": canopy_item.get("licenseInfo"),
                              "reuse_terms_status": "Public CMAP service with no redistribution license specified; Ecopia-derived canopy. Clarify reuse terms before publishing.",
                              "canopy_missing_chicago_geo_ids": sorted(ids - {f["attributes"]["geoid_tract"] for f in canopy["features"]})},
            "housing_source": {**housing_provenance, "metadata_url": HOUSING_METADATA_URL,
                               "acs_year": ACS_YEAR, "estimate_period": "2020-2024",
                               "terms_url": "https://www.census.gov/about/policies/copyright.html",
                               "reuse_terms_status": "US federal Census aggregate statistics, generally public domain; attribute ACS table and vintage",
                               "rate_denominator": "Renter-occupied units paying cash rent with computable rent/income ratio (B25070 categories 2-10)",
                               "missing_policy": "Negative sentinels/annotations become null; missing components propagate; zero denominator gives null rate",
                               "moe_policy": "90% source count MOEs; approximate sum MOE=root sum of squared component MOEs; rate MOEs not computed"},
        }
    retrieved_at = manifest["retrieved_at"]
    datasets = {"tract_tree_canopy": normalize_canopy(canopy, ids, retrieved_at),
                "tract_housing_burden": normalize_housing(housing, ids, retrieved_at)}
    manifest["normalized"] = {table: save_rows(output_dir, table, rows) for table, rows in datasets.items()}
    write_json(output_dir / "manifest.json", manifest)
    for table, rows in datasets.items():
        print(f"Saved {len(rows):,} Chicago-overlapping tract rows to {output_dir / (table + '.jsonl')}")
        if args.load:
            print(f"Appended to {load_bigquery(table, rows, args.project, args.dataset, args.location)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Environment acquisition failed: {error}", file=sys.stderr)
        sys.exit(1)
