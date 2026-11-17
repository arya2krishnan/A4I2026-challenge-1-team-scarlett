#!/usr/bin/env python3
"""Fetch CTA GTFS and save normalized snapshots; --load opts into new BigQuery tables.

    python scripts/load_chicago_transit.py
    python scripts/load_chicago_transit.py --service-date 2026-11-18

The full CTA network includes service outside Chicago. Scheduled departures are
for a GTFS service date in America/Chicago, not live arrivals or route accessibility.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import sys
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

URL = "https://www.transitchicago.com/downloads/sch_data/google_transit.zip"
TERMS_URL = "https://www.transitchicago.com/developers/terms/"
SOURCE_PAGE = "https://www.transitchicago.com/developers/gtfs/"
SCHEMAS = {
    "transit_stops": [("stop_id", "STRING"), ("stop_name", "STRING"),
                      ("latitude", "FLOAT64"), ("longitude", "FLOAT64"),
                      ("location_type", "INT64"), ("parent_station", "STRING"),
                      ("wheelchair_boarding", "INT64")],
    "transit_routes": [("route_id", "STRING"), ("route_short_name", "STRING"),
                       ("route_long_name", "STRING"), ("route_type", "INT64")],
    "transit_calendar": [("service_id", "STRING"), ("start_date", "DATE"),
                         ("end_date", "DATE")] + [(day, "BOOL") for day in
                         ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")],
    "transit_calendar_dates": [("service_id", "STRING"), ("date", "DATE"),
                               ("exception_type", "INT64")],
    "transit_departures": [("service_date", "DATE"), ("stop_id", "STRING"),
                           ("route_id", "STRING"), ("service_hour", "INT64"),
                           ("scheduled_departures", "INT64"),
                           ("first_departure_seconds", "INT64"), ("last_departure_seconds", "INT64"),
                           ("timezone", "STRING")],
}
PROVENANCE = [("source", "STRING"), ("retrieved_at", "TIMESTAMP")]


def fetch() -> bytes:
    req = urllib.request.Request(URL, headers={"User-Agent": "heat-dispatch-agent/1.0"})
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.read()


def gtfs_rows(archive: zipfile.ZipFile, name: str):
    """Stream CSV inside ZIP; no extraction to disk or third-party dependencies."""
    if name not in archive.namelist():
        return
    with archive.open(name) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def as_int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def iso_date(value: str) -> str:
    return dt.datetime.strptime(value, "%Y%m%d").date().isoformat()


def normalize_stops(records, retrieved_at: str) -> list[dict]:
    rows = []
    for record in records:
        try:
            lat, lon = float(record["stop_lat"]), float(record["stop_lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not record.get("stop_id") or not math.isfinite(lat) or not math.isfinite(lon):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        rows.append({"stop_id": record["stop_id"], "stop_name": record.get("stop_name", ""),
                     "latitude": lat, "longitude": lon,
                     "location_type": as_int(record.get("location_type")),
                     "parent_station": record.get("parent_station") or None,
                     "wheelchair_boarding": as_int(record.get("wheelchair_boarding")),
                     "source": URL, "retrieved_at": retrieved_at})
    return rows


def active_services(calendar: list[dict], exceptions: list[dict], service_date: dt.date) -> set[str]:
    day = service_date.strftime("%A").lower()
    date = service_date.isoformat()
    active = {r["service_id"] for r in calendar
              if r["start_date"] <= date <= r["end_date"] and r[day]}
    for record in exceptions:
        if record["date"] == date:
            if record["exception_type"] == 1:
                active.add(record["service_id"])
            elif record["exception_type"] == 2:
                active.discard(record["service_id"])
    return active


def departure_seconds(value: str) -> int:
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    if hours < 0 or not (0 <= minutes < 60 and 0 <= seconds < 60):
        raise ValueError(f"invalid GTFS departure {value!r}")
    return hours * 3600 + minutes * 60 + seconds


def summarize_departures(records, trips: dict[str, str], service_date: dt.date,
                        retrieved_at: str) -> tuple[list[dict], int]:
    """Count scheduled, boardable departures by route, stop and GTFS service hour.

    GTFS hours can exceed 23. Frequency-template trips are excluded upstream.
    Missing times and pickup_type=1 (no pickup) do not become boardable service.
    """
    groups: dict[tuple[str, str, int], list[int]] = defaultdict(list)
    skipped = 0
    for record in records:
        route = trips.get(record.get("trip_id", ""))
        if route is None or record.get("pickup_type") == "1":
            continue
        try:
            seconds = departure_seconds(record.get("departure_time", ""))
        except (ValueError, TypeError):
            skipped += 1
            continue
        if not record.get("stop_id"):
            skipped += 1
            continue
        groups[(record["stop_id"], route, seconds // 3600)].append(seconds)
    rows = [{"service_date": service_date.isoformat(), "stop_id": stop,
             "route_id": route, "service_hour": hour, "scheduled_departures": len(seconds),
             "first_departure_seconds": min(seconds), "last_departure_seconds": max(seconds),
             "timezone": "America/Chicago", "source": URL, "retrieved_at": retrieved_at}
            for (stop, route, hour), seconds in sorted(groups.items())]
    return rows, skipped


def normalize_feed(payload: bytes, service_date: dt.date, retrieved_at: str) -> tuple[dict, dict]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        raw_stops = list(gtfs_rows(archive, "stops.txt"))
        stops = normalize_stops(raw_stops, retrieved_at)
        routes = [{"route_id": r["route_id"], "route_short_name": r.get("route_short_name", ""),
                   "route_long_name": r.get("route_long_name", ""), "route_type": as_int(r.get("route_type")),
                   "source": URL, "retrieved_at": retrieved_at}
                  for r in gtfs_rows(archive, "routes.txt")]
        weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        calendar = [{"service_id": r["service_id"], "start_date": iso_date(r["start_date"]),
                     "end_date": iso_date(r["end_date"]), **{d: r.get(d) == "1" for d in weekdays},
                     "source": URL, "retrieved_at": retrieved_at}
                    for r in gtfs_rows(archive, "calendar.txt")]
        exceptions = [{"service_id": r["service_id"], "date": iso_date(r["date"]),
                       "exception_type": as_int(r["exception_type"]), "source": URL,
                       "retrieved_at": retrieved_at}
                      for r in gtfs_rows(archive, "calendar_dates.txt")]
        active = active_services(calendar, exceptions, service_date)
        frequencies = {r["trip_id"] for r in gtfs_rows(archive, "frequencies.txt")}
        trips = {r["trip_id"]: r["route_id"] for r in gtfs_rows(archive, "trips.txt")
                 if r["service_id"] in active and r["trip_id"] not in frequencies}
        departures, missing_times = summarize_departures(gtfs_rows(archive, "stop_times.txt"), trips,
                                                        service_date, retrieved_at)
    tables = {"transit_stops": stops, "transit_routes": routes, "transit_calendar": calendar,
              "transit_calendar_dates": exceptions, "transit_departures": departures}
    details = {"service_date": service_date.isoformat(), "active_service_ids": sorted(active),
               "active_scheduled_trips": len(trips), "frequency_template_trips_excluded": len(frequencies),
               "invalid_stops_dropped": len(raw_stops) - len(stops),
               "active_departures_with_missing_or_invalid_times": missing_times,
               "schedule_start": min((r["start_date"] for r in calendar), default=None),
               "schedule_end": max((r["end_date"] for r in calendar), default=None)}
    return tables, details


def write_snapshot(output_dir: Path, tables: dict, manifest: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for table, rows in tables.items():
        with (output_dir / f"{table}.jsonl").open("w") as handle:
            for row in rows:
                handle.write(json.dumps(row, allow_nan=False) + "\n")
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def load_tables(tables: dict, project: str, dataset: str, location: str) -> None:
    from google.cloud.bigquery.client import Client
    from google.cloud.bigquery.job.load import LoadJobConfig
    from google.cloud.bigquery.schema import SchemaField

    client = Client(project=project, location=location)
    for name, rows in tables.items():
        if not rows:
            print(f"skipping empty {name}; existing table, if any, is unchanged")
            continue
        target = f"{project}.{dataset}.{name}"
        config = LoadJobConfig(schema=[SchemaField(n, t) for n, t in SCHEMAS[name] + PROVENANCE],
                                       write_disposition="WRITE_TRUNCATE")
        client.load_table_from_json(rows, target, job_config=config).result()
        print(f"loaded {len(rows):,} rows into {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, default=Path(".data/enrichment/transit"))
    parser.add_argument("--service-date", type=dt.date.fromisoformat,
                        default=dt.datetime.now(ZoneInfo("America/Chicago")).date())
    parser.add_argument("--source-zip", type=Path, help="Normalize an already downloaded official feed")
    parser.add_argument("--load", action="store_true")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument("--dataset", default=os.environ.get("BQ_DATASET", "a4i_climate"))
    parser.add_argument("--location", default=os.environ.get("BQ_LOCATION", "US"))
    args = parser.parse_args()
    if args.load and not args.project:
        parser.error("--load requires --project or GOOGLE_CLOUD_PROJECT")
    retrieved_at = dt.datetime.now(dt.timezone.utc).isoformat()
    payload = args.source_zip.read_bytes() if args.source_zip else fetch()
    if args.source_zip:
        cached_manifest = args.source_zip.parent / "manifest.json"
        if cached_manifest.exists():
            cached = json.loads(cached_manifest.read_text())
            if cached.get("sha256") == hashlib.sha256(payload).hexdigest():
                retrieved_at = cached["retrieved_at"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "google_transit.zip").write_bytes(payload)
    tables, details = normalize_feed(payload, args.service_date, retrieved_at)
    manifest = {"source": URL, "source_page": SOURCE_PAGE, "terms_url": TERMS_URL,
                "retrieved_at": retrieved_at, "sha256": hashlib.sha256(payload).hexdigest(),
                "source_bytes": len(payload), "coverage": "Entire CTA service network, including suburbs",
                "normalized_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "row_counts": {name: len(rows) for name, rows in tables.items()}, **details,
                "limitations": ["Static scheduled service; no current disruption or live arrival data",
                                "Nearest stop alone does not establish a trip to cooling",
                                "wheelchair_boarding=0 or null means unknown; parent station rules may apply",
                                "Service hours >=24 belong to the next clock day of the selected service date",
                                "Frequency-template trips excluded from departure counts",
                                "CTA license limits use to rider assistance or promoting public transportation; this snapshot supports transit access to cooling"]}
    write_snapshot(args.output_dir, tables, manifest)
    print(json.dumps({"output_dir": str(args.output_dir), "counts": manifest["row_counts"], **details}, indent=2))
    if not details["active_service_ids"]:
        print("WARNING: selected service date has no active service in this feed; departure snapshot is empty")
    if args.load:
        load_tables(tables, args.project, args.dataset, args.location)
    return 0


if __name__ == "__main__":
    sys.exit(main())
