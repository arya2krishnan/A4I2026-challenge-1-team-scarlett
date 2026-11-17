#!/usr/bin/env python3
"""Acquire aligned ACS2024 estimates/MOEs for Cook County and Chicago tracts.

Reuses the existing, verified ACS2024 social-source subsets and acquires B08201
household/vehicle, B17001 poverty, B01002 median-age and B19013 median-household-
income data from official keyless summary files.
Writes local raw subsets, normalized JSONL, explicit BigQuery schema and source
manifest. Does not write BigQuery or change existing vulnerability rankings.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable

from load_chicago_vulnerability import SELECTED as SOCIAL_FIELDS
from load_chicago_vulnerability import aggregate, ratio, source_url

ROOT = Path(__file__).resolve().parents[1]
ACS_YEAR = 2024
EXPECTED_COOK_TRACTS = 1332
TABLE_FIELDS = {**SOCIAL_FIELDS, "B08201": [1, 2], "B17001": [1, 2], "B01002": [1], "B19013": [1]}
UNIVERSES = {
    "population_universe": "Total population (B01001)",
    "older_population_universe": "Population 65 years and over (B09020)",
    "household_universe": "Households (B08201)",
    "poverty_population_universe": "Population for whom poverty status is determined (B17001)",
    "disability_population_universe": "Civilian noninstitutionalized population (B18101)",
    "median_age_universe": "Total population (B01002); median age in years",
    "median_household_income_universe": "Households (B19013); median income in 2024 inflation-adjusted US dollars",
}
COUNT_DEFINITIONS = {
    "total_population": ("B01001", [1]),
    "population_65_plus": ("B09020", [1]),
    "households": ("B08201", [1]),
    "no_vehicle_households": ("B08201", [2]),
    "poverty_universe_population": ("B17001", [1]),
    "population_below_poverty": ("B17001", [2]),
    "older_adults_living_alone": ("B09020", [15, 18]),
    "civilian_noninstitutionalized_population": ("B18101", [1]),
    "people_with_disability": ("B18101", SOCIAL_FIELDS["B18101"][1:]),
    "children_under_5": ("B01001", [3, 27]),
}
MEDIAN_DEFINITIONS = {"median_age": ("B01002", [1]), "median_household_income": ("B19013", [1])}
MEASURE_DEFINITIONS = {**COUNT_DEFINITIONS, **MEDIAN_DEFINITIONS}
RATE_DEFINITIONS = {
    "population_65_plus_rate": ("population_65_plus", "total_population"),
    "no_vehicle_rate": ("no_vehicle_households", "households"),
    "poverty_rate": ("population_below_poverty", "poverty_universe_population"),
    "older_adults_living_alone_rate": ("older_adults_living_alone", "population_65_plus"),
    "disability_rate": ("people_with_disability", "civilian_noninstitutionalized_population"),
    "children_under_5_rate": ("children_under_5", "total_population"),
}
SCHEMA = [
    ("geo_id", "STRING"), ("acs_year", "INTEGER"), ("estimate_period", "STRING"),
    ("geographic_scope", "STRING"), ("source", "STRING"), ("retrieved_at", "TIMESTAMP"),
    *[(field, "STRING") for field in UNIVERSES],
    *[(field, "FLOAT64") for name in MEASURE_DEFINITIONS for field in (name, f"{name}_moe")],
    *[(field, "FLOAT64") for field in RATE_DEFINITIONS],
]


def request(url: str) -> Any:
    return urllib.request.urlopen(urllib.request.Request(
        url, headers={"User-Agent": "heat-dispatch-agent/1.0 (ACS2024 alignment)"}), timeout=120)


def metadata_url(table: str) -> str:
    return f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5/groups/{table}.json"


def verify_metadata(metadata: dict[str, Any], table: str) -> None:
    variables = metadata.get("variables", {})
    for component in TABLE_FIELDS[table]:
        for suffix in ("E", "M"):
            if f"{table}_{component:03d}{suffix}" not in variables:
                raise ValueError(f"ACS2024 {table} selected fields are missing")
    required_labels = {
        "B08201": {2: "!!No vehicle available"},
        "B17001": {2: "!!Income in the past 12 months below poverty level:"},
        "B09020": {15: "!!Living alone", 18: "!!Living alone"},
        "B01001": {3: "!!Under 5 years", 27: "!!Under 5 years"},
        "B18101": {component: "!!With a disability" for component in TABLE_FIELDS["B18101"][1:]},
        "B01002": {1: "Estimate!!Median age --!!Total:"},
        "B19013": {1: "Estimate!!Median household income in the past 12 months (in 2024 inflation-adjusted dollars)"},
    }
    for component, label in required_labels[table].items():
        if not variables[f"{table}_{component:03d}E"]["label"].endswith(label):
            raise ValueError(f"ACS2024 {table} selected field definitions changed")


def parse_summary(lines: Iterable[bytes], table: str) -> dict[str, dict[str, str]]:
    iterator = iter(lines)
    try:
        columns = next(iterator).decode("utf-8-sig").rstrip("\r\n").split("|")
    except StopIteration as exc:
        raise ValueError("Empty Census summary file") from exc
    expected = [f"{table}_{suffix}{component:03d}" for component in TABLE_FIELDS[table] for suffix in ("E", "M")]
    if columns[0] != "GEO_ID" or not set(expected) <= set(columns):
        raise ValueError(f"ACS {table} summary-file columns changed")
    indexes = {field: columns.index(field) for field in expected}
    rows = {}
    for raw in iterator:
        if not raw.startswith(b"1400000US17031"):
            continue
        values = raw.decode("utf-8").rstrip("\r\n").split("|")
        if len(values) != len(columns):
            raise ValueError(f"Malformed {table} summary row")
        geo_id = values[0].removeprefix("1400000US")
        if len(geo_id) != 11 or not geo_id.isdigit() or geo_id in rows:
            raise ValueError(f"Invalid or duplicate {table} tract key")
        rows[geo_id] = {field: values[indexes[field]] for field in expected}
    if not rows:
        raise ValueError(f"No Cook County tracts in {table}")
    return rows


def fetch_table(table: str) -> tuple[dict[str, dict[str, str]], dict[str, Any], dict[str, Any]]:
    with request(metadata_url(table)) as response:
        metadata = json.load(response)
    verify_metadata(metadata, table)
    digest = hashlib.sha256()
    byte_count = 0

    def hashed_lines(response: Any) -> Iterable[bytes]:
        nonlocal byte_count
        for line in response:
            digest.update(line)
            byte_count += len(line)
            yield line

    url = source_url(ACS_YEAR, table)
    with request(url) as response:
        rows = parse_summary(hashed_lines(response), table)
    return rows, metadata, {"table": table, "acs_year": ACS_YEAR, "url": url,
                            "metadata_url": metadata_url(table), "source_sha256": digest.hexdigest(),
                            "downloaded_bytes": byte_count, "county_rows": len(rows), "acquisition": "official bulk file"}


def normalize(tables: dict[str, dict[str, dict[str, str]]], retrieved_at: str) -> list[dict[str, Any]]:
    if set(tables) != set(TABLE_FIELDS):
        raise ValueError("All seven ACS2024 tables are required")
    tract_ids = set(tables["B01001"])
    if any(set(rows) != tract_ids for rows in tables.values()):
        raise ValueError("ACS2024 table tract coverage differs; refusing a partial join")
    output = []
    for geo_id in sorted(tract_ids):
        if len(geo_id) != 11 or not geo_id.isdigit() or not geo_id.startswith("17031"):
            raise ValueError(f"Expected Cook County tract key, got {geo_id}")
        row: dict[str, Any] = {
            "geo_id": geo_id, "acs_year": ACS_YEAR, "estimate_period": "2020-2024",
            "geographic_scope": "Cook County, Illinois census tract; whole-tract ACS estimates",
            "source": "Census ACS2024 5-year B01001, B09020, B18101, B08201, B17001, B01002, B19013",
            "retrieved_at": retrieved_at, **UNIVERSES,
        }
        for field, (table, components) in MEASURE_DEFINITIONS.items():
            row[field] = aggregate(tables[table][geo_id], table, components, "E")
            row[f"{field}_moe"] = aggregate(tables[table][geo_id], table, components, "M")
        for field, (numerator, denominator) in RATE_DEFINITIONS.items():
            row[field] = ratio(row[numerator], row[denominator])
            if row[field] is not None and not 0 <= row[field] <= 1:
                raise ValueError(f"Inconsistent population universes for {geo_id} {field}")
        output.append(row)
    return output


def select_chicago(rows: list[dict[str, Any]], tract_path: Path) -> list[dict[str, Any]]:
    boundaries = [json.loads(line) for line in tract_path.read_text().splitlines() if line.strip()]
    ids = [row["geo_id"] for row in boundaries]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Chicago tract boundary keys are empty or duplicated")
    if any(row.get("acs_year") != ACS_YEAR for row in boundaries):
        raise ValueError("Chicago boundary vintage must match ACS2024")
    source_ids = {row["geo_id"] for row in rows}
    if set(ids) - source_ids:
        raise ValueError("Chicago-intersecting tract is absent from aligned ACS source")
    selected_ids = set(ids)
    return [{**row, "geographic_scope": "Cook County tract intersecting ACS2024 Census Chicago place; whole-tract estimates"}
            for row in rows if row["geo_id"] in selected_ids]


def save_json(path: Path, data: Any) -> str:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_jsonl(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    path.write_text("".join(json.dumps(row, allow_nan=False) + "\n" for row in rows))
    return {"file": path.name, "rows": len(rows), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "null_counts": {field: sum(row[field] is None for row in rows) for field, _ in SCHEMA}}


def acquire_social_cache(social_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    manifest_path = social_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("acs_year") != ACS_YEAR or manifest.get("estimate_period") != "2020-2024":
        raise ValueError("Existing social cache must be ACS2024 (2020-2024)")
    tables: dict[str, Any] = {}
    sources = []
    for table in SOCIAL_FIELDS:
        raw_path = social_dir / f"{table}_cook_county_raw.json"
        metadata_path = social_dir / f"{table}_metadata.json"
        raw = json.loads(raw_path.read_text())
        metadata = json.loads(metadata_path.read_text())
        verify_metadata(metadata, table)
        original = next((source for source in manifest["sources"] if source["table"] == table), None)
        if original is None or original.get("url") != source_url(ACS_YEAR, table):
            raise ValueError(f"Cached {table} source provenance does not match ACS2024")
        expected = {f"{table}_{suffix}{component:03d}" for component in SOCIAL_FIELDS[table] for suffix in ("E", "M")}
        if any(set(row) != expected for row in raw.values()):
            raise ValueError(f"Cached {table} selected columns differ")
        tables[table] = {"raw": raw, "metadata": metadata}
        sources.append({"table": table, "acs_year": ACS_YEAR, "url": original["url"],
                        "metadata_url": metadata_url(table), "source_sha256": original.get("sha256"),
                        "downloaded_bytes": original.get("downloaded_bytes"), "county_rows": len(raw),
                        "acquisition": "verified existing ACS2024 source subset",
                        "original_retrieved_at": manifest["retrieved_at"], "original_raw_path": str(raw_path),
                        "original_raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest()})
    return tables, sources, manifest


def acquire_extra_table(table: str, output_dir: Path) -> tuple[dict[str, dict[str, str]], dict[str, Any], dict[str, Any]]:
    """Reuse this loader's validated same-year sources, otherwise acquire the official file."""
    manifest_path = output_dir / "manifest.json"
    raw_path = output_dir / f"{table}_cook_county_raw.json"
    metadata_path = output_dir / f"{table}_metadata.json"
    if manifest_path.exists() and raw_path.exists() and metadata_path.exists():
        previous = json.loads(manifest_path.read_text())
        source = next((item for item in previous.get("sources", []) if item["table"] == table), None)
        if source is not None and previous.get("acs_year") == ACS_YEAR:
            if source.get("url") != source_url(ACS_YEAR, table):
                raise ValueError(f"Cached {table} source year/URL differs")
            if hashlib.sha256(raw_path.read_bytes()).hexdigest() != source["retained_raw_sha256"]:
                raise ValueError(f"Cached {table} raw subset hash differs")
            if hashlib.sha256(metadata_path.read_bytes()).hexdigest() != source["metadata_sha256"]:
                raise ValueError(f"Cached {table} metadata hash differs")
            metadata = json.loads(metadata_path.read_text())
            verify_metadata(metadata, table)
            source = {**source, "acquisition": "verified existing aligned ACS2024 source subset",
                      "original_retrieved_at": source.get("original_retrieved_at", previous["retrieved_at"])}
            return json.loads(raw_path.read_text()), metadata, source
    return fetch_table(table)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/enrichment/acs_aligned")
    parser.add_argument("--social-dir", type=Path, default=ROOT / "data/enrichment/vulnerability")
    parser.add_argument("--tracts", type=Path, default=ROOT / "data/enrichment/geography/tract_boundaries_chicago.jsonl")
    parser.add_argument("--from-cache", action="store_true", help="Normalize this acquisition's retained raw sources without network calls")
    args = parser.parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.from_cache:
        manifest = json.loads((output_dir / "manifest.json").read_text())
        if manifest.get("acs_year") != ACS_YEAR:
            raise ValueError("Aligned cache must be ACS2024")
        if manifest["chicago_tract_input_sha256"] != hashlib.sha256(args.tracts.read_bytes()).hexdigest():
            raise ValueError("Chicago tract boundary input changed; reacquire alignment")
        tables = {}
        for table in TABLE_FIELDS:
            path = output_dir / f"{table}_cook_county_raw.json"
            source = next(source for source in manifest["sources"] if source["table"] == table)
            if hashlib.sha256(path.read_bytes()).hexdigest() != source["retained_raw_sha256"]:
                raise ValueError(f"Cached {table} raw subset hash differs")
            tables[table] = json.loads(path.read_text())
    else:
        social, sources, social_manifest = acquire_social_cache(args.social_dir)
        tables = {table: value["raw"] for table, value in social.items()}
        metadata = {table: value["metadata"] for table, value in social.items()}
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {table: pool.submit(acquire_extra_table, table, output_dir)
                       for table in ("B08201", "B17001", "B01002", "B19013")}
            for table, future in futures.items():
                tables[table], metadata[table], source = future.result()
                sources.append(source)
                print(f"{table}: acquired {len(tables[table]):,} Cook County tracts", flush=True)
        if any(len(rows) != EXPECTED_COOK_TRACTS for rows in tables.values()):
            raise ValueError("Expected all 1,332 ACS2024 Cook County census tracts")
        for source in sources:
            table = source["table"]
            source["retained_raw_sha256"] = save_json(output_dir / f"{table}_cook_county_raw.json", tables[table])
            source["metadata_sha256"] = save_json(output_dir / f"{table}_metadata.json", metadata[table])
        retrieved_at = dt.datetime.now(dt.timezone.utc).isoformat()
        manifest = {
            "acs_year": ACS_YEAR, "estimate_period": "2020-2024", "retrieved_at": retrieved_at,
            "sources": sources, "chicago_tract_input_path": str(args.tracts),
            "chicago_tract_input_sha256": hashlib.sha256(args.tracts.read_bytes()).hexdigest(),
            "social_source_manifest_sha256": hashlib.sha256((args.social_dir / "manifest.json").read_bytes()).hexdigest(),
            "social_source_retrieved_at": social_manifest["retrieved_at"],
            "universe_definitions": UNIVERSES, "count_components": COUNT_DEFINITIONS,
            "median_fields": MEDIAN_DEFINITIONS,
            "rate_definitions": RATE_DEFINITIONS,
            "missing_policy": "Negative Census sentinel values, nonnumeric annotations and nonfinite values become null; missing components propagate; zero denominators give null rates",
            "moe_policy": "90% source count MOEs; sum MOE approximated by root sum of squared component MOEs (no covariance); rate MOEs not computed",
            "city_selection": "Use saved ACS2024 Census Chicago place/tract positive-area overlap; whole-tract estimates retained",
            "geographic_limit": "Cook County source only; Chicago's DuPage County portion is not represented",
            "terms_url": "https://www.census.gov/about/policies/copyright.html",
            "publication_state": "local acquisition only; no BigQuery writes or vulnerability-weight changes",
        }
    county_rows = normalize(tables, manifest["retrieved_at"])
    city_rows = select_chicago(county_rows, args.tracts)
    manifest["outputs"] = {
        "cook": save_jsonl(output_dir / "tract_acs_2024_cook.jsonl", county_rows),
        "chicago": save_jsonl(output_dir / "tract_acs_2024_chicago.jsonl", city_rows),
    }
    manifest["schema_sha256"] = save_json(output_dir / "schema.json", [{"name": name, "type": kind, "mode": "NULLABLE"} for name, kind in SCHEMA])
    save_json(output_dir / "manifest.json", manifest)
    print(f"Saved {len(county_rows):,} Cook County and {len(city_rows):,} Chicago-intersecting ACS2024 tract rows")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ACS alignment failed: {error}", file=sys.stderr)
        sys.exit(1)
