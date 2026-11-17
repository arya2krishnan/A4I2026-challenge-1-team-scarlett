import load_chicago_facilities as lf


def rec(t, lon=-87.64, lat=41.78, **kw):
    return {"site_type": t, "site_name": "N", "address": "A", "location": {"type": "Point", "coordinates": [lon, lat]}, **kw}


def test_normalize_flags_indoor_and_drops_bad_points():
    rows = lf.normalize([rec("Library"), rec("Park District Spray Feature"), rec("Library", lat=0.0),
                         {"site_type": "Library", "location": None}, rec("Police District", lon=-122.0)])
    assert [r["facility_type"] for r in rows] == ["Library", "Park District Spray Feature"]
    assert [r["is_indoor"] for r in rows] == [True, False]
    assert rows[0]["latitude"] == 41.78 and rows[0]["longitude"] == -87.64
