#!/usr/bin/env python3
"""Snapshot City of Chicago open data on places people can go to cool down, as CSV + BigQuery schemas.

Writes data/chicago/sites/ :
  cooling_centers.csv        official City cooling network (DFSS/OEMC "Cooling Centers", msrk-w9ih)
  libraries.csv              every Chicago Public Library branch with weekly hours (x8fc-8rcq)
  police_stations.csv        CPD district stations, open 24/7 for heat relief (z8bn-74gv)
  senior_centers.csv         DFSS regional + satellite senior centers (qhfc-4cw2)
  cps_schools.csv            CPS school locations SY2025-26 (pb6d-zzuh): candidate sites, NOT cooling sites today
  candidate_sites.csv        one tidy table: all current cooling sites + CPS high schools as expansion candidates
  manifest.json              dataset ids, URLs, row counts, sha256, retrieval time
  bq_schemas/<name>.json     BigQuery schema for each CSV (used by tools/load_chicago_sites_bq.sh)

Standard library only. Every run fully rewrites the folder, so re-running is always safe.

    python tools/fetch_chicago_sites.py                 # fetch from data.cityofchicago.org
    python tools/fetch_chicago_sites.py --out /tmp/x    # write somewhere else
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

PORTAL = "https://data.cityofchicago.org"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "chicago" / "sites"

# name -> (Socrata id, title, preferred column order). Columns not listed are kept, appended alphabetically,
# so a new field on the portal is never silently dropped.
DATASETS = {
    "cooling_centers": ("msrk-w9ih", "Cooling Centers",
                        ["site_type", "site_name", "address", "city", "state", "zip", "phone", "hours_of_operation"]),
    "libraries": ("x8fc-8rcq", "Libraries - Locations, Contact Information, and Usual Hours of Service",
                  ["name_", "address", "city", "state", "zip", "phone", "hours_of_operation", "website"]),
    "police_stations": ("z8bn-74gv", "Police Stations",
                        ["district", "district_name", "address", "city", "state", "zip", "phone", "fax", "tty", "website"]),
    "senior_centers": ("qhfc-4cw2", "Senior Centers",
                       ["program", "site_name", "address", "city", "state", "zip", "phone", "hours_of_operation"]),
    "cps_schools": ("pb6d-zzuh", "Chicago Public Schools - School Locations SY2526",
                    ["school_id", "short_name", "address", "grade_cat"]),
}

# Socrata bookkeeping and raw geometry: replaced by latitude/longitude columns.
DROP = {"location", "the_geom", "lat", "long", "latitude", "longitude", "x_coordinate", "y_coordinate"}
CHI_BBOX = (41.60, 42.05, -87.95, -87.50)  # lat_min, lat_max, lon_min, lon_max

# The City says only the Park District facilities LISTED in the cooling dataset are air-conditioned;
# spray features (splash pads) are outdoors. Everything else in the dataset is an indoor, cooled building.
OUTDOOR_COOLING_TYPES = {"Park District Spray Feature"}


def fetch_json(dataset_id: str, tries: int = 4) -> list[dict]:
    url = f"{PORTAL}/resource/{dataset_id}.json?$limit=50000&$order=:id"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "a4i2026-team-scarlett/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001  retry transient portal errors
            if i == tries - 1:
                raise
            print(f"  retry {dataset_id}: {e}", file=sys.stderr)
            time.sleep(2 ** i)
    return []


def point(rec: dict) -> tuple[float | None, float | None]:
    """lat, lon from whichever geometry shape this dataset uses."""
    for la, lo in (("latitude", "longitude"), ("lat", "long")):
        if rec.get(la) not in (None, "") and rec.get(lo) not in (None, ""):
            try:
                return float(rec[la]), float(rec[lo])
            except (TypeError, ValueError):
                pass
    for key in ("location", "the_geom"):
        g = rec.get(key)
        if isinstance(g, dict):
            if g.get("coordinates"):
                try:
                    return float(g["coordinates"][1]), float(g["coordinates"][0])
                except (TypeError, ValueError, IndexError):
                    pass
            if g.get("latitude") not in (None, ""):
                try:
                    return float(g["latitude"]), float(g["longitude"])
                except (TypeError, ValueError):
                    pass
    return None, None


def clean(v) -> str:
    if v is None:
        return ""
    if isinstance(v, dict):  # e.g. website: {"url": ...}
        v = v.get("url") or v.get("description") or json.dumps(v, sort_keys=True)
    return re.sub(r"\s+", " ", str(v)).strip()


def normalize(name: str, records: list[dict], retrieved_at: str) -> tuple[list[str], list[dict], dict]:
    dataset_id, _, preferred = DATASETS[name]
    rows, stats = [], {"fetched": len(records), "no_point": 0, "outside_chicago": 0}
    for r in records:
        lat, lon = point(r)
        if lat is None:
            stats["no_point"] += 1
        row = {k: clean(v) for k, v in r.items() if not k.startswith(":") and k not in DROP}
        row["latitude"] = "" if lat is None else f"{lat:.7f}"
        row["longitude"] = "" if lon is None else f"{lon:.7f}"
        in_chi = lat is not None and CHI_BBOX[0] <= lat <= CHI_BBOX[1] and CHI_BBOX[2] <= lon <= CHI_BBOX[3]
        if lat is not None and not in_chi:
            stats["outside_chicago"] += 1
        row["in_chicago_bbox"] = "true" if in_chi else "false"
        if name == "cooling_centers":
            row["indoor_air_conditioned"] = "false" if row.get("site_type") in OUTDOOR_COOLING_TYPES else "true"
        if name == "cps_schools":
            row["is_high_school"] = "true" if row.get("grade_cat", "").upper() == "HS" else "false"
        row["source_dataset_id"] = dataset_id
        row["retrieved_at"] = retrieved_at
        rows.append(row)
    tail = ["latitude", "longitude", "in_chicago_bbox", "indoor_air_conditioned", "is_high_school",
            "source_dataset_id", "retrieved_at"]
    seen = set().union(*[r.keys() for r in rows]) if rows else set()
    cols = [c for c in preferred if c in seen]
    cols += sorted(c for c in seen if c not in cols and c not in tail)
    cols += [c for c in tail if c in seen]
    stats["kept"] = len(rows)
    return cols, rows, stats


CANDIDATE_COLS = ["site_key", "site_name", "site_category", "operator", "address", "zip", "latitude", "longitude",
                  "is_current_cooling_site", "indoor_air_conditioned", "open_24_7", "hours_of_operation",
                  "source_dataset_id", "retrieved_at"]
OPERATOR = {"Library": "Chicago Public Library", "Police District": "Chicago Police Department",
            "Community Service Center": "DFSS", "Regional Senior Center": "DFSS", "Satellite Senior Center": "DFSS",
            "Chicago Community College": "City Colleges of Chicago", "Park District Facility": "Chicago Park District",
            "Park District Spray Feature": "Chicago Park District"}


def candidates(cooling: list[dict], schools: list[dict]) -> list[dict]:
    """Current cooling network + CPS high schools as candidate expansion sites (flagged, never mixed up)."""
    out = []
    for i, r in enumerate(cooling):
        t = r.get("site_type", "")
        out.append({"site_key": f"cool-{i + 1:04d}", "site_name": r.get("site_name", ""), "site_category": t,
                    "operator": OPERATOR.get(t, ""), "address": r.get("address", ""), "zip": r.get("zip", ""),
                    "latitude": r["latitude"], "longitude": r["longitude"], "is_current_cooling_site": "true",
                    "indoor_air_conditioned": r.get("indoor_air_conditioned", ""),
                    "open_24_7": "true" if t == "Police District" else "false",
                    "hours_of_operation": r.get("hours_of_operation", ""), "source_dataset_id": r["source_dataset_id"],
                    "retrieved_at": r["retrieved_at"]})
    for r in schools:
        if r.get("is_high_school") != "true":
            continue
        out.append({"site_key": f"cps-{r.get('school_id', '')}", "site_name": r.get("short_name", ""),
                    "site_category": "CPS High School (candidate)", "operator": "Chicago Public Schools",
                    "address": r.get("address", ""), "zip": r.get("zip", ""), "latitude": r["latitude"],
                    "longitude": r["longitude"], "is_current_cooling_site": "false", "indoor_air_conditioned": "",
                    "open_24_7": "false", "hours_of_operation": "", "source_dataset_id": r["source_dataset_id"],
                    "retrieved_at": r["retrieved_at"]})
    return out


def bq_schema(cols: list[str]) -> list[dict]:
    def typ(c):
        if c in ("latitude", "longitude"):
            return "FLOAT64"
        if c in ("in_chicago_bbox", "indoor_air_conditioned", "is_high_school", "is_current_cooling_site", "open_24_7"):
            return "BOOL"
        if c == "retrieved_at":
            return "TIMESTAMP"
        return "STRING"  # zips, phone numbers, ids: keep leading zeros and dashes
    return [{"name": c, "type": typ(c), "mode": "NULLABLE"} for c in cols]


def write_csv(path: Path, cols: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    data = buf.getvalue().encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    out = args.out
    (out / "bq_schemas").mkdir(parents=True, exist_ok=True)
    retrieved_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    manifest = {"retrieved_at": retrieved_at, "portal": PORTAL, "tool": "tools/fetch_chicago_sites.py", "files": {}}
    tables = {}
    for name, (dataset_id, title, _) in DATASETS.items():
        cols, rows, stats = normalize(name, fetch_json(dataset_id), retrieved_at)
        tables[name] = rows
        sha = write_csv(out / f"{name}.csv", cols, rows)
        (out / "bq_schemas" / f"{name}.json").write_text(json.dumps(bq_schema(cols), indent=2) + "\n")
        manifest["files"][f"{name}.csv"] = {"dataset_id": dataset_id, "title": title,
                                            "landing_page": f"{PORTAL}/d/{dataset_id}",
                                            "api": f"{PORTAL}/resource/{dataset_id}.json",
                                            "rows": len(rows), "sha256": sha, **stats}
        print(f"{name:16s} {dataset_id}  {len(rows):4d} rows  (no point: {stats['no_point']}, "
              f"outside Chicago: {stats['outside_chicago']})")
    cand = candidates(tables["cooling_centers"], tables["cps_schools"])
    sha = write_csv(out / "candidate_sites.csv", CANDIDATE_COLS, cand)
    (out / "bq_schemas" / "candidate_sites.json").write_text(json.dumps(bq_schema(CANDIDATE_COLS), indent=2) + "\n")
    manifest["files"]["candidate_sites.csv"] = {"derived_from": ["cooling_centers.csv", "cps_schools.csv"],
                                                "rows": len(cand), "sha256": sha}
    print(f"candidate_sites  derived   {len(cand):4d} rows")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
