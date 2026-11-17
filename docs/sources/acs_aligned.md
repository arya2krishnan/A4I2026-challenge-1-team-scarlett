# Aligned ACS2024 vulnerability inputs

Priority 1 in `docs/DATA_WORK_PLAN.md` requires a consistent Census vintage after correcting cell-to-tract geography. This acquisition supplies **2024 ACS five-year estimates (2020–2024)**, including estimate universes and margins of error, for all **1,332 Cook County census tracts** and the **799 tracts intersecting Chicago's ACS2024 Census place boundary**.

The loader writes local artifacts only. It does not write BigQuery, replace existing demographics, adjust vulnerability weights, or change the heat model's labels or spatial split.

## Source tables and definitions

Official keyless source-file pattern:

`https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-TABLE.dat`

`TABLE` is lowercase, such as `b08201`. Variable metadata follows `https://api.census.gov/data/2024/acs/acs5/groups/B08201.json`. Selected estimate/MOE fields and relevant variable labels are checked against the official metadata before acquisition or cache reuse.

| Measure | ACS source | Universe / unit |
|---|---|---|
| `total_population` | B01001 `_001` | Total population; people |
| `population_65_plus` | B09020 `_001` | Population age 65 and over; people |
| `households` | B08201 `_001` | Households |
| `no_vehicle_households` | B08201 `_002` | Households with no vehicle available |
| `poverty_universe_population` | B17001 `_001` | Population for whom poverty status is determined |
| `population_below_poverty` | B17001 `_002` | People in the B17001 universe whose income in the past 12 months was below poverty level |
| `older_adults_living_alone` | B09020 `_015` + `_018` | People age 65+ living alone |
| `civilian_noninstitutionalized_population` | B18101 `_001` | Civilian noninstitutionalized population |
| `people_with_disability` | B18101 `_004`, `_007`, `_010`, `_013`, `_016`, `_019`, `_023`, `_026`, `_029`, `_032`, `_035`, `_038` | All disjoint age/sex groups with disability in the civilian noninstitutionalized population |
| `children_under_5` | B01001 `_003` + `_027` | Children younger than five; people |
| `median_age` | B01002 `_001` | Total population; median age in years |
| `median_household_income` | B19013 `_001` | Households; median annual income in **2024 inflation-adjusted US dollars** |

Each measure has a corresponding `_moe` field. In the table-based bulk format the estimate field is `B08201_E002`, while the metadata API calls it `B08201_002E`; the loader handles that naming difference explicitly.

Three social source subsets (B01001, B09020, B18101) are reused from the existing verified ACS2024 acquisition. Their original retrieval times, full-source hashes, source URLs, local subset hashes, and metadata are retained in the aligned manifest. B08201, B17001, B01002, and B19013 were acquired from official bulk files. Subsequent normal runs reuse the aligned raw source subsets if their ACS year, source URL, raw hash, metadata hash, and field definitions match. `--from-cache` makes no network requests.

## Rates retain distinct denominators

All rates are fractions in `[0,1]`:

| Rate | Numerator / denominator |
|---|---|
| `population_65_plus_rate` | Population 65+ / total population |
| `no_vehicle_rate` | No-vehicle households / households |
| `poverty_rate` | Population below poverty / population for whom poverty status is determined |
| `older_adults_living_alone_rate` | Older adults living alone / population 65+ |
| `disability_rate` | People with disability / civilian noninstitutionalized population |
| `children_under_5_rate` | Children younger than five / total population |

The poverty denominator is not total population, and vehicle access is a household measure. Universe descriptions are stored in each normalized row. Values outside the expected rate range fail as an inconsistent-universe check.

Negative Census sentinel values, nonnumeric annotations, and nonfinite values remain unknown (`null`). Missing components propagate to a sum. A zero denominator gives a null rate. Source count/median MOEs use 90% confidence. A summed count's MOE is approximated by the square root of the sum of squared component MOEs; this omits covariance. Direct medians retain their direct source MOEs. Rate MOEs are not calculated. See [Census ACS guidance](https://www.census.gov/programs-surveys/acs/guidance/handbooks/general.html).

Some medians have estimates without usable MOEs, including source-special/top-coded cases. A missing MOE is not zero uncertainty.

## Geographic coverage

The Chicago subset uses the saved **ACS2024 Census Chicago incorporated-place / tract positive-area overlap**, preserving whole-tract estimates. It has 799 rows. Boundary files must have the matching ACS2024 vintage, unique keys, and complete source coverage. This is a **Cook County** acquisition; Chicago's DuPage County portion is outside its scope.

Do not sum tract population after joining it to every grid cell, and do not claim that an intersecting tract's entire population lives inside Chicago. Border tract values are not apportioned by land area.

The county output intentionally includes tract **17031820901**. The existing cell **13923_-21936** falls in that tract even though it is excluded from the primary 799-tract city subset. This supports the root geography workflow's explicit boundary-discrepancy handling and its 800-tract union of primary city and mapped edge tracts. It does not change the source city's boundary or population allocation.

## Acquired coverage and checks

- All seven source tables contain the same **1,332 unique Cook County tract IDs**.
- County and city normalized files have respectively **1,332 and 799 unique rows**, all ACS2024.
- All acquired count estimates and count MOEs are present in both extents.
- The county has four zero-denominator tracts; the city subset has three. Their rates are null.
- County median age has four null estimates/MOEs; median household income has 22 null estimates and 29 null MOEs.
- City median age has three null estimates/MOEs; median household income has 19 null estimates and 20 null MOEs.
- Cache replay produces the same normalized source snapshot. The manifest records source and output hashes, null counts, schemas, universe definitions, and exact numerator/denominator definitions.

## Run

```bash
.venv/bin/python scripts/load_chicago_acs_aligned.py
.venv/bin/python scripts/load_chicago_acs_aligned.py --from-cache
.venv/bin/python -m pytest tests/test_acs_aligned.py -q
.venv/bin/python -m mypy --follow-imports=silent --ignore-missing-imports scripts/load_chicago_acs_aligned.py
```

Defaults:

- Social sources: `data/enrichment/vulnerability/`.
- Chicago boundary keys: `data/enrichment/geography/tract_boundaries_chicago.jsonl`.
- Output: `data/enrichment/acs_aligned/`.

Output files:

- `tract_acs_2024_cook.jsonl` and `tract_acs_2024_chicago.jsonl`.
- `schema.json`: explicit nullable BigQuery field schema; the Python loader exports the same 43-field list as `SCHEMA`.
- `manifest.json`: vintage, source hashes, cached-source retrieval times, scope, measures, universes, rates, and output checks.
- A retained Cook County raw subset and metadata JSON for each of the seven ACS tables.

Acquisition and normalization use the Python standard library plus existing normalization helpers. Tests use `pytest`; typechecking uses `mypy`. No cloud credentials are required.

## Terms

Census-produced aggregate statistics are US federal government data and generally public domain. Attribute the US Census Bureau, ACS2024 five-year estimates, and table IDs. The [Census copyright policy](https://www.census.gov/about/policies/copyright.html) is the terms reference; that policy HTML page returned HTTP 403 in this environment during the original social acquisition, while source files and metadata were directly accessible. This dataset contains aggregate public statistics and no race fields or individual resident records.
