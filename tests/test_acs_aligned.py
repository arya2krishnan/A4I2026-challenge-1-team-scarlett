import json

import pytest

import load_chicago_acs_aligned as aligned


def tables():
    result = {}
    for table, components in aligned.TABLE_FIELDS.items():
        result[table] = {"17031010100": {f"{table}_{suffix}{component:03d}": "1" if suffix == "E" else "3"
                                          for component in components for suffix in ("E", "M")}}
    estimates = {
        "B01001": {1: "1000", 3: "25", 27: "35"},
        "B09020": {1: "100", 15: "10", 18: "20"},
        "B18101": {1: "950"}, "B08201": {1: "400", 2: "80"},
        "B17001": {1: "800", 2: "80"}, "B01002": {1: "38.4"}, "B19013": {1: "62000"},
    }
    for table, components in estimates.items():
        for component, value in components.items():
            result[table]["17031010100"][f"{table}_E{component:03d}"] = value
    result["B09020"]["17031010100"]["B09020_M015"] = "3"
    result["B09020"]["17031010100"]["B09020_M018"] = "4"
    return result


def test_population_household_and_poverty_rates_use_distinct_universes():
    row = aligned.normalize(tables(), "2026-11-17T00:00:00Z")[0]
    assert row["population_65_plus_rate"] == 0.1
    assert row["no_vehicle_rate"] == 0.2
    assert row["poverty_rate"] == 0.1
    assert row["poverty_universe_population"] == 800
    assert row["older_adults_living_alone"] == 30
    assert row["older_adults_living_alone_rate"] == 0.3
    assert row["older_adults_living_alone_moe"] == 5
    assert row["people_with_disability"] == 12
    assert row["disability_rate"] == pytest.approx(12 / 950)
    assert row["children_under_5_rate"] == 0.06
    assert row["median_age"] == 38.4
    assert row["median_household_income"] == 62000
    assert row["acs_year"] == 2024
    assert "2024 inflation-adjusted" in row["median_household_income_universe"]
    assert set(row) == {name for name, _ in aligned.SCHEMA}


def test_missing_direct_moe_and_zero_poverty_universe_remain_unknown():
    source = tables()
    source["B08201"]["17031010100"]["B08201_M002"] = "-555555555"
    source["B17001"]["17031010100"]["B17001_E001"] = "0"
    row = aligned.normalize(source, "2026-11-17T00:00:00Z")[0]
    assert row["no_vehicle_households"] == 80
    assert row["no_vehicle_households_moe"] is None
    assert row["poverty_rate"] is None


def test_missing_social_component_propagates_without_destroying_other_data():
    source = tables()
    source["B09020"]["17031010100"]["B09020_E015"] = "-666666666"
    source["B19013"]["17031010100"]["B19013_M001"] = "-333333333"
    row = aligned.normalize(source, "2026-11-17T00:00:00Z")[0]
    assert row["older_adults_living_alone"] is None
    assert row["older_adults_living_alone_rate"] is None
    assert row["median_household_income"] == 62000
    assert row["median_household_income_moe"] is None
    assert row["no_vehicle_rate"] == 0.2


def test_partial_source_coverage_is_rejected():
    source = tables()
    source["B17001"] = {}
    with pytest.raises(ValueError, match="coverage differs"):
        aligned.normalize(source, "2026-11-17T00:00:00Z")


def test_inconsistent_universes_are_rejected():
    source = tables()
    source["B08201"]["17031010100"]["B08201_E002"] = "500"
    with pytest.raises(ValueError, match="Inconsistent population universes"):
        aligned.normalize(source, "2026-11-17T00:00:00Z")


def test_chicago_selection_preserves_whole_tract_counts_and_checks_vintage(tmp_path):
    rows = aligned.normalize(tables(), "2026-11-17T00:00:00Z")
    boundary = tmp_path / "boundaries.jsonl"
    boundary.write_text(json.dumps({"geo_id": "17031010100", "acs_year": 2024}) + "\n")
    selected = aligned.select_chicago(rows, boundary)
    assert selected[0]["total_population"] == 1000
    assert "whole-tract estimates" in selected[0]["geographic_scope"]
    boundary.write_text(json.dumps({"geo_id": "17031010100", "acs_year": 2022}) + "\n")
    with pytest.raises(ValueError, match="vintage must match"):
        aligned.select_chicago(rows, boundary)


def test_duplicate_boundary_keys_are_rejected(tmp_path):
    boundary = tmp_path / "boundaries.jsonl"
    boundary.write_text((json.dumps({"geo_id": "17031010100", "acs_year": 2024}) + "\n") * 2)
    with pytest.raises(ValueError, match="duplicated"):
        aligned.select_chicago(aligned.normalize(tables(), "2026-11-17T00:00:00Z"), boundary)


def test_summary_parser_retains_cook_tracts_and_raw_sentinels():
    lines = [b"GEO_ID|B08201_E001|B08201_M001|B08201_E002|B08201_M002\n",
             b"0500000US17031|10|2|3|4\n", b"1400000US17031010100|10|2|3|-555555555\n",
             b"1400000US17043010100|10|2|3|4\n"]
    parsed = aligned.parse_summary(lines, "B08201")
    assert list(parsed) == ["17031010100"]
    assert parsed["17031010100"]["B08201_M002"] == "-555555555"
    with pytest.raises(ValueError, match="duplicate"):
        aligned.parse_summary([lines[0], lines[2], lines[2]], "B08201")
