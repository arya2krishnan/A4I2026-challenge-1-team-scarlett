import datetime as dt

from load_chicago_cooling_inventory import normalize_inventory
from load_chicago_transit import active_services, normalize_stops, summarize_departures


def test_calendar_exception_addition_and_removal_override_weekday():
    calendar = [{"service_id": "weekday", "start_date": "2026-11-01", "end_date": "2026-11-30",
                 "tuesday": True}]
    exceptions = [{"service_id": "weekday", "date": "2026-11-17", "exception_type": 2},
                  {"service_id": "special", "date": "2026-11-17", "exception_type": 1}]
    assert active_services(calendar, exceptions, dt.date(2026, 11, 17)) == {"special"}


def test_departures_preserve_after_midnight_and_exclude_no_pickup():
    rows, skipped = summarize_departures([
        {"trip_id": "active", "stop_id": "001", "departure_time": "25:10:00"},
        {"trip_id": "active", "stop_id": "001", "departure_time": "25:30:00"},
        {"trip_id": "active", "stop_id": "001", "departure_time": "25:40:00", "pickup_type": "1"},
        {"trip_id": "inactive", "stop_id": "001", "departure_time": "25:50:00"},
        {"trip_id": "active", "stop_id": "002", "departure_time": ""},
    ], {"active": "R"}, dt.date(2026, 11, 17), "2026-11-17T00:00:00Z")
    assert skipped == 1
    assert len(rows) == 1
    assert rows[0]["scheduled_departures"] == 2
    assert rows[0]["service_hour"] == 25
    assert rows[0]["first_departure_seconds"] == 90600
    assert rows[0]["service_date"] == "2026-11-17"


def test_stop_unknown_accessibility_and_bad_coordinates():
    rows = normalize_stops([
        {"stop_id": "001", "stop_lat": "41.8", "stop_lon": "-87.6", "wheelchair_boarding": "0"},
        {"stop_id": "002", "stop_lat": "41.8", "stop_lon": "-87.6", "parent_station": "station"},
        {"stop_id": "bad", "stop_lat": "NaN", "stop_lon": "-87.6"},
    ], "2026-11-17T00:00:00Z")
    assert len(rows) == 2
    assert rows[0]["stop_id"] == "001"
    assert rows[0]["wheelchair_boarding"] == 0
    assert rows[1]["wheelchair_boarding"] is None
    assert rows[1]["parent_station"] == "station"


def test_cooling_snapshot_preserves_hours_and_unknown_readiness():
    rows = normalize_inventory([{"site_type": "Library", "site_name": "Library",
                                 "hours_of_operation": "M-F 9am-5pm; Holidays closed",
                                 "location": {"coordinates": [-87.64, 41.78]}}],
                               "2026-11-17T00:00:00Z")
    assert rows[0]["hours_of_operation"] == "M-F 9am-5pm; Holidays closed"
    assert rows[0]["is_indoor"] is True
    for field in ("open_for_event", "available_capacity", "working_ac_confirmed", "staffing_confirmed",
                  "wheelchair_accessible_confirmed", "readiness_verified_at"):
        assert rows[0][field] is None
