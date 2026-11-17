"""Unit/coverage checks for NWS enrichment, with no network or GCP dependencies."""
import datetime as dt

import pytest

from load_chicago_weather import CHICAGO, normalize_hourly, summarize_daily


def payload(periods):
    return {"properties": {
        "updateTime": "2026-11-17T12:00:00-06:00",
        "generatedAt": "2026-11-17T18:10:00Z", "periods": periods,
    }}


def period(start="2026-11-17T12:00:00-06:00", end="2026-11-17T13:00:00-06:00", **extra):
    return {"startTime": start, "endTime": end, "temperature": 30,
            "temperatureUnit": "C", "isDaytime": True, "windSpeed": "5 to 10 mph",
            "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": 55},
            "dewpoint": {"unitCode": "wmoUnit:degC", "value": 15}, **extra}


def normalize(periods):
    return normalize_hourly(payload(periods), "LOT/76,73", "Loop", 41.8781, -87.6298,
                            "https://api.weather.gov/gridpoints/LOT/76,73/forecast/hourly",
                            "2026-11-17T18:20:00Z")


def test_units_missing_humidity_and_utc_provenance():
    row = normalize([period(relativeHumidity={"unitCode": "wmoUnit:percent", "value": None})])[0]
    assert row["temperature_f"] == 86
    assert row["relative_humidity_pct"] is None
    assert row["dewpoint_c"] == 15
    assert row["valid_start"] == "2026-11-17T18:00:00+00:00"
    assert row["forecast_issued_at"] == "2026-11-17T18:00:00+00:00"
    assert row["local_hour"] == 12
    assert row["wind_speed_text"] == "5 to 10 mph"


def test_unknown_units_and_invalid_humidity_remain_null():
    row = normalize([period(temperatureUnit="K", dewpoint={"unitCode": "unknown", "value": 15},
                            relativeHumidity={"unitCode": "wmoUnit:percent", "value": 110})])[0]
    assert row["temperature_f"] is None
    assert row["dewpoint_c"] is None
    assert row["relative_humidity_pct"] is None


def test_duplicate_forecast_period_rejected():
    with pytest.raises(ValueError, match="duplicate forecast period"):
        normalize([period(), period()])


@pytest.mark.parametrize("date,expected_hours", [("2026-03-07", 11), ("2026-10-31", 13)])
def test_overnight_coverage_uses_elapsed_hours_across_dst(date, expected_hours):
    date = dt.date.fromisoformat(date)
    start = dt.datetime.combine(date, dt.time(20), CHICAGO).astimezone(dt.timezone.utc)
    end = dt.datetime.combine(date + dt.timedelta(days=1), dt.time(8), CHICAGO).astimezone(dt.timezone.utc)
    periods = []
    cursor = start
    while cursor < end:
        next_hour = cursor + dt.timedelta(hours=1)
        periods.append(period(cursor.isoformat(), next_hour.isoformat(), temperature=80,
                              temperatureUnit="F", isDaytime=False))
        cursor = next_hour
    summary = next(row for row in summarize_daily(normalize(periods)) if row["local_date"] == date.isoformat())
    assert summary["overnight_expected_hours"] == expected_hours
    assert summary["overnight_covered_hours"] == expected_hours
    assert summary["overnight_complete"] is True
    assert summary["overnight_low_f"] == 80


def test_partial_night_and_missing_temperature_do_not_look_complete():
    rows = normalize([
        period("2026-11-17T20:00:00-06:00", "2026-11-17T21:00:00-06:00", temperature=80, temperatureUnit="F"),
        period("2026-11-17T21:00:00-06:00", "2026-11-17T22:00:00-06:00", temperature=None),
    ])
    summary = summarize_daily(rows)[0]
    assert summary["overnight_covered_hours"] == 1
    assert summary["overnight_expected_hours"] == 12
    assert summary["overnight_complete"] is False
    assert summary["overnight_low_f"] == 80
