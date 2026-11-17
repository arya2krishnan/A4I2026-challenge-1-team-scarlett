#!/usr/bin/env python3
"""Fetch current Chicago NWS hourly forecasts and overnight summaries.

Default: save source responses, normalized JSONL, and a provenance manifest locally.
Opt in to loading the NEW weather_hourly/weather_daily tables with --load.
These are forecasts at retrieval time, not observations from the Heat Watch campaign.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

NWS = "https://api.weather.gov"
CHICAGO = ZoneInfo("America/Chicago")
USER_AGENT = "heat-dispatch-agent/1.0 (Chicago urban heat research)"
POINTS = [
    ("Loop", 41.8781, -87.6298),
    ("Rogers Park", 42.0094, -87.6696),
    ("Austin", 41.8917, -87.7600),
    ("Englewood", 41.7798, -87.6456),
    ("South Shore", 41.7606, -87.5741),
    ("Pullman", 41.6922, -87.6064),
]

HOURLY_SCHEMA = [
    ("grid_key", "STRING"), ("point_names", "STRING"),
    ("latitude", "FLOAT64"), ("longitude", "FLOAT64"),
    ("valid_start", "TIMESTAMP"), ("valid_end", "TIMESTAMP"),
    ("local_date", "DATE"), ("local_hour", "INT64"), ("is_daytime", "BOOL"),
    ("temperature_f", "FLOAT64"), ("relative_humidity_pct", "FLOAT64"),
    ("dewpoint_c", "FLOAT64"), ("wind_speed_text", "STRING"),
    ("wind_direction", "STRING"), ("short_forecast", "STRING"),
    ("forecast_issued_at", "TIMESTAMP"), ("forecast_generated_at", "TIMESTAMP"),
    ("retrieved_at", "TIMESTAMP"), ("source", "STRING"),
]
DAILY_SCHEMA = [
    ("grid_key", "STRING"), ("point_names", "STRING"),
    ("latitude", "FLOAT64"), ("longitude", "FLOAT64"), ("local_date", "DATE"),
    ("forecast_high_f", "FLOAT64"), ("forecast_low_f", "FLOAT64"),
    ("day_covered_hours", "FLOAT64"), ("day_expected_hours", "FLOAT64"),
    ("day_complete", "BOOL"), ("overnight_low_f", "FLOAT64"),
    ("overnight_covered_hours", "FLOAT64"), ("overnight_expected_hours", "FLOAT64"),
    ("overnight_complete", "BOOL"), ("overnight_start", "TIMESTAMP"),
    ("overnight_end", "TIMESTAMP"), ("forecast_issued_at", "TIMESTAMP"),
    ("forecast_generated_at", "TIMESTAMP"), ("retrieved_at", "TIMESTAMP"),
    ("source", "STRING"),
]


def timestamp(value: str | None) -> str | None:
    """Store all forecast and provenance timestamps in UTC."""
    if value is None:
        return None
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("forecast timestamp must contain a timezone")
    return parsed.astimezone(dt.timezone.utc).isoformat()


def number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def quantitative(value: object, allowed_units: set[str]) -> float | None:
    if not isinstance(value, dict) or value.get("unitCode") not in allowed_units:
        return None
    return number(value.get("value"))


def normalize_hourly(payload: dict, grid_key: str, point_names: str,
                     latitude: float, longitude: float, source: str,
                     retrieved_at: str) -> list[dict]:
    properties = payload["properties"]
    rows = []
    seen = set()
    for period in properties.get("periods", []):
        start, end = timestamp(period["startTime"]), timestamp(period["endTime"])
        if start is None or end is None or end <= start:
            raise ValueError("forecast period must have a positive duration")
        if start in seen:
            raise ValueError(f"duplicate forecast period for {grid_key}: {start}")
        seen.add(start)
        local = dt.datetime.fromisoformat(start).astimezone(CHICAGO)
        temperature = number(period.get("temperature"))
        if temperature is not None:
            unit = period.get("temperatureUnit")
            if unit == "C":
                temperature = temperature * 9 / 5 + 32
            elif unit != "F":
                temperature = None
        humidity = quantitative(period.get("relativeHumidity"), {"wmoUnit:percent"})
        if humidity is not None and not 0 <= humidity <= 100:
            humidity = None
        rows.append({
            "grid_key": grid_key, "point_names": point_names,
            "latitude": latitude, "longitude": longitude,
            "valid_start": start, "valid_end": end,
            "local_date": local.date().isoformat(), "local_hour": local.hour,
            "is_daytime": period.get("isDaytime"), "temperature_f": temperature,
            "relative_humidity_pct": humidity,
            "dewpoint_c": quantitative(period.get("dewpoint"), {"wmoUnit:degC"}),
            "wind_speed_text": period.get("windSpeed"),
            "wind_direction": period.get("windDirection"),
            "short_forecast": period.get("shortForecast"),
            "forecast_issued_at": timestamp(properties.get("updateTime")),
            "forecast_generated_at": timestamp(properties.get("generatedAt")),
            "retrieved_at": timestamp(retrieved_at), "source": source,
        })
    return rows


def _coverage(rows: list[dict], start: dt.datetime, end: dt.datetime) -> tuple[float, list[float]]:
    intervals, temperatures = [], []
    for row in rows:
        left = max(start, dt.datetime.fromisoformat(row["valid_start"]))
        right = min(end, dt.datetime.fromisoformat(row["valid_end"]))
        if left < right and row["temperature_f"] is not None:
            intervals.append((left, right))
            temperatures.append(row["temperature_f"])
    # Merge intervals to avoid falsely marking duplicated/overlapping rows complete.
    merged: list[tuple[dt.datetime, dt.datetime]] = []
    for left, right in sorted(intervals):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    return sum((right - left).total_seconds() / 3600 for left, right in merged), temperatures


def summarize_daily(rows: list[dict]) -> list[dict]:
    """Night starts at 20:00 local date and ends at 08:00 the following day.

    Partial days/nights have explicit coverage; DST changes expected hour counts.
    Temperatures are extrema of available hourly forecasts, not observed extrema.
    """
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["grid_key"], []).append(row)
    output = []
    for key, periods in sorted(grouped.items()):
        dates = set()
        for row in periods:
            local = dt.datetime.fromisoformat(row["valid_start"]).astimezone(CHICAGO)
            dates.add(local.date())
            if local.hour < 8:
                dates.add(local.date() - dt.timedelta(days=1))
        first = periods[0]
        for date in sorted(dates):
            tomorrow = date + dt.timedelta(days=1)
            start = dt.datetime.combine(date, dt.time(0), CHICAGO).astimezone(dt.timezone.utc)
            end = dt.datetime.combine(tomorrow, dt.time(0), CHICAGO).astimezone(dt.timezone.utc)
            night_start = dt.datetime.combine(date, dt.time(20), CHICAGO).astimezone(dt.timezone.utc)
            night_end = dt.datetime.combine(tomorrow, dt.time(8), CHICAGO).astimezone(dt.timezone.utc)
            day_hours, day_temps = _coverage(periods, start, end)
            night_hours, night_temps = _coverage(periods, night_start, night_end)
            expected_day = (end - start).total_seconds() / 3600
            expected_night = (night_end - night_start).total_seconds() / 3600
            output.append({
                "grid_key": key, "point_names": first["point_names"],
                "latitude": first["latitude"], "longitude": first["longitude"],
                "local_date": date.isoformat(),
                "forecast_high_f": max(day_temps) if day_temps else None,
                "forecast_low_f": min(day_temps) if day_temps else None,
                "day_covered_hours": day_hours, "day_expected_hours": expected_day,
                "day_complete": math.isclose(day_hours, expected_day),
                "overnight_low_f": min(night_temps) if night_temps else None,
                "overnight_covered_hours": night_hours,
                "overnight_expected_hours": expected_night,
                "overnight_complete": math.isclose(night_hours, expected_night),
                "overnight_start": night_start.isoformat(), "overnight_end": night_end.isoformat(),
                "forecast_issued_at": first["forecast_issued_at"],
                "forecast_generated_at": first["forecast_generated_at"],
                "retrieved_at": first["retrieved_at"], "source": first["source"],
            })
    return output


def get_json(url: str, user_agent: str = USER_AGENT) -> dict:
    request = urllib.request.Request(url, headers={
        "User-Agent": user_agent, "Accept": "application/geo+json",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, allow_nan=False) + "\n"
    path.write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def fetch_weather(output_dir: Path, user_agent: str = USER_AGENT) -> tuple[list[dict], list[dict], dict]:
    retrieved_at = dt.datetime.now(dt.timezone.utc).isoformat()
    grids: dict[str, dict] = {}
    sources, errors = [], []
    for name, latitude, longitude in POINTS:
        url = f"{NWS}/points/{latitude:.4f},{longitude:.4f}"
        try:
            payload = get_json(url, user_agent)
            digest = write_json(output_dir / "raw" / f"point_{name.lower().replace(' ', '_')}.json", payload)
            properties = payload["properties"]
            key = f"{properties['gridId']}/{properties['gridX']},{properties['gridY']}"
            sources.append({"url": url, "sha256": digest})
            if key in grids:
                grids[key]["names"].append(name)
            else:
                grids[key] = {"names": [name], "latitude": latitude, "longitude": longitude,
                              "url": properties["forecastHourly"]}
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as error:
            errors.append({"point": name, "url": url, "error": str(error)})
    rows = []
    for key, grid in grids.items():
        try:
            payload = get_json(grid["url"], user_agent)
            digest = write_json(output_dir / "raw" / f"hourly_{key.replace('/', '_').replace(',', '_')}.json", payload)
            rows.extend(normalize_hourly(payload, key, " | ".join(grid["names"]),
                                         grid["latitude"], grid["longitude"], grid["url"], retrieved_at))
            sources.append({"url": grid["url"], "sha256": digest})
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as error:
            errors.append({"grid_key": key, "url": grid["url"], "error": str(error)})
    daily = summarize_daily(rows)
    manifest = {
        "retrieved_at": retrieved_at, "provider": "National Weather Service / NOAA",
        "data_kind": "current forecast; not historical observations",
        "license": "US government NWS forecasts: public domain; NOAA disclaimers apply",
        "terms_url": "https://www.weather.gov/disclaimer",
        "api_documentation": "https://www.weather.gov/documentation/services-web-api",
        "timezone": "America/Chicago", "temperature_unit": "F", "dewpoint_unit": "C",
        "humidity_unit": "percent", "wind_unit": "original NWS text (usually mph)",
        "overnight_definition": "20:00 local date through 08:00 the next day; coverage is DST-aware",
        "coverage": "Six representative Chicago points, deduplicated by NWS forecast grid. Not every city cell.",
        "requested_points": len(POINTS), "resolved_grids": len(grids),
        "successful_grids": len({row['grid_key'] for row in rows}),
        "hourly_rows": len(rows), "daily_rows": len(daily),
        "valid_start": min((row["valid_start"] for row in rows), default=None),
        "valid_end": max((row["valid_end"] for row in rows), default=None),
        "sources": sources, "errors": errors,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for table, values in (("weather_hourly", rows), ("weather_daily", daily)):
        (output_dir / f"{table}.jsonl").write_text("".join(json.dumps(row, allow_nan=False) + "\n" for row in values))
    write_json(output_dir / "manifest.json", manifest)
    return rows, daily, manifest


def load_tables(project: str, dataset: str, location: str,
                hourly: list[dict], daily: list[dict]) -> None:
    from google.cloud.bigquery.client import Client
    from google.cloud.bigquery.job.load import LoadJobConfig
    from google.cloud.bigquery.schema import SchemaField

    client = Client(project=project, location=location)
    for table, rows, schema in (("weather_hourly", hourly, HOURLY_SCHEMA),
                                ("weather_daily", daily, DAILY_SCHEMA)):
        if not rows:
            raise ValueError(f"refusing to replace {table} with an empty forecast")
        target = f"{project}.{dataset}.{table}"
        client.load_table_from_json(rows, target, job_config=LoadJobConfig(
            schema=[SchemaField(name, kind) for name, kind in schema],
            write_disposition="WRITE_TRUNCATE",
        )).result()
        print(f"loaded {len(rows)} rows into {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/enrichment/weather"))
    parser.add_argument("--user-agent", default=os.environ.get("NWS_USER_AGENT", USER_AGENT))
    parser.add_argument("--load", action="store_true", help="load the new weather tables into BigQuery")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument("--dataset", default=os.environ.get("BQ_DATASET", "a4i_climate"))
    parser.add_argument("--location", default=os.environ.get("BQ_LOCATION", "US"))
    args = parser.parse_args()
    if args.load and not args.project:
        parser.error("--load requires --project or GOOGLE_CLOUD_PROJECT")
    hourly, daily, manifest = fetch_weather(args.output_dir, args.user_agent)
    print(json.dumps({key: manifest[key] for key in (
        "retrieved_at", "successful_grids", "hourly_rows", "daily_rows", "valid_start", "valid_end", "errors",
    )}, indent=2))
    if not hourly:
        print("No forecasts acquired; see manifest errors.", file=sys.stderr)
        return 1
    if args.load:
        load_tables(args.project, args.dataset, args.location, hourly, daily)
    return 0


if __name__ == "__main__":
    sys.exit(main())
