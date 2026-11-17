import math

import pytest

import load_chicago_environment as le


def canopy_raw(value=0.25):
    return {"features": [{"attributes": {"geoid_tract": "17031010100", "county_fips": "17031", "forest": value}},
                         {"attributes": {"geoid_tract": "17031010201", "county_fips": "17031", "forest": 0.4}}]}


def test_canopy_preserves_fraction_and_converts_to_percentage():
    rows = le.normalize_canopy(canopy_raw(), {"17031010100"}, "2026-11-17T00:00:00Z")
    assert len(rows) == 1
    row = rows[0]
    assert row["tree_canopy_fraction"] == 0.25
    assert row["tree_canopy_percent"] == 25
    assert row["canopy_imagery_year"] == 2023
    assert "unspecified" in row["reuse_terms_status"]
    assert set(row) == {name for name, _ in le.CANOPY_SCHEMA}


def test_canopy_does_not_guess_if_source_units_change():
    with pytest.raises(ValueError, match="unit changed"):
        le.normalize_canopy(canopy_raw(25), {"17031010100"}, "2026-11-17T00:00:00Z")


def test_missing_canopy_is_not_zero():
    row = le.normalize_canopy(canopy_raw(None), {"17031010100"}, "2026-11-17T00:00:00Z")[0]
    assert row["tree_canopy_fraction"] is None
    assert row["tree_canopy_percent"] is None


def housing_raw():
    fields = {f"B25070_{suffix}{component:03d}": "10" if suffix == "E" else "3"
              for component in range(1, 12) for suffix in ("E", "M")}
    fields["B25070_E001"] = "100"
    return {"17031010100": fields}


def test_housing_burden_excludes_uncomputable_ratios_from_denominator():
    row = le.normalize_housing(housing_raw(), {"17031010100"}, "2026-11-17T00:00:00Z")[0]
    assert row["computed_rent_burden_units"] == 90
    assert row["rent_burden_30_plus_units"] == 40
    assert row["rent_burden_30_plus_units_moe"] == 6
    assert row["rent_burden_50_plus_units"] == 10
    assert row["rent_burden_50_plus_units_moe"] == 3
    assert row["computed_rent_burden_units_moe"] == math.sqrt(81)
    assert row["rent_burden_30_plus_rate"] == pytest.approx(40 / 90)
    assert row["rent_burden_50_plus_rate"] == pytest.approx(10 / 90)
    assert row["rent_burden_not_computed_rate"] == 0.1
    assert set(row) == {name for name, _ in le.HOUSING_SCHEMA}


def test_missing_component_propagates_to_housing_rate():
    raw = housing_raw()
    raw["17031010100"]["B25070_E008"] = "-666666666"
    row = le.normalize_housing(raw, {"17031010100"}, "2026-11-17T00:00:00Z")[0]
    assert row["rent_burden_30_plus_units"] is None
    assert row["rent_burden_30_plus_rate"] is None
    assert row["rent_burden_50_plus_units"] == 10


def test_housing_missing_city_tract_is_rejected():
    with pytest.raises(ValueError, match="lacks 1 Chicago tracts"):
        le.normalize_housing(housing_raw(), {"17031010201"}, "2026-11-17T00:00:00Z")


def test_zero_rent_paying_population_gives_null_rates():
    raw = housing_raw()
    raw["17031010100"] = {key: "0" for key in raw["17031010100"]}
    row = le.normalize_housing(raw, {"17031010100"}, "2026-11-17T00:00:00Z")[0]
    assert row["rent_burden_30_plus_rate"] is None
    assert row["rent_burden_not_computed_rate"] is None
