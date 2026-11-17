# Tree canopy and housing-cost burden

Two actual datasets are saved for **799 Cook County census tracts that intersect Chicago's Census city boundary**. The tract set comes from `scripts/clip_chicago_vulnerability.py`. Values describe whole tracts, including the portion outside Chicago for border tracts. Do not treat polygon clipping as a population allocation.

## Tree canopy: CMAP / Ecopia 2023

Source: [CMAP Heat Vulnerability Index public feature layer](https://services5.arcgis.com/LcMXE3TFhi1BSaCY/arcgis/rest/services/Heat_Vulnerability_Index/FeatureServer/0), [source item metadata](https://www.arcgis.com/sharing/rest/content/items/2144b38119a04066b33d710048362f91?f=json), and [methodology report](https://cmap.illinois.gov/wp-content/uploads/dlm_uploads/Heat-vulnerability-index-methodology-report.pdf).

The source `forest` field is explicitly labeled “Percentage of census tract area with tree canopy.” Its numeric values are fractions in `[0,1]`; the loader preserves them as `tree_canopy_fraction` and multiplies by 100 for `tree_canopy_percent`. Values outside the expected unit range fail rather than being silently rescaled. This measures canopy coverage, distinct from OpenStreetMap park or green-space polygons.

The methodology report, **Table 5 on PDF page 12 / printed page 11**, identifies the canopy source as **Ecopia imagery from 2023**, published in CMAP's **2026** HVI. The input data is not all from 2022 despite the source item's general description. CMAP states that Ecopia imagery and derived spatial datasets were acquired with IDOT and NOAA support.

Only `geoid_tract`, `county_fips`, and `forest` are requested and retained. The composite HVI score, health measures, demographics, and principal-component scores are excluded. This prevents adopting an unvalidated composite risk score into the dispatch model.

The official county source returned **1,331 tracts**. All 799 Chicago tract IDs were present; **795 had usable canopy values and four were null**. Observed valid coverage ranged from approximately **0.84% to 68.61%**. Null canopy is unknown, never zero. Tract averages do not identify shade along a particular sidewalk or street corner.

### Canopy terms

The ArcGIS item has `access: public` but **`licenseInfo: null`**; the service also specifies no copyright or redistribution terms. The canopy is derived from Ecopia data. Public query access supports local acquisition, but an open redistribution license has **not** been established. The ignored local snapshot and manifest retain that limitation. Clarify CMAP/Ecopia reuse terms before public redistribution or treating this as a confirmed open-license challenge dataset. Credit CMAP, the 2026 HVI, and Ecopia 2023 imagery in any permitted use.

## Housing cost burden: Census ACS 2024 B25070

Source: [official table-based summary file](https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b25070.dat), [Census variable metadata](https://api.census.gov/data/2024/acs/acs5/groups/B25070.json).

**2024 ACS 5-year estimates cover 2020–2024.** B25070 measures **gross rent as a percentage of household income** among renter-occupied housing units paying cash rent. It can identify areas where household finances may constrain options during a heat emergency. It does not measure energy burden, AC ownership, the cost of running AC, or indoor temperature.

The loader retains estimates and 90% margins of error for:

| Output count | B25070 source categories |
|---|---|
| `rent_paying_units` | Total, `_001` |
| `computed_rent_burden_units` | Computable rent/income categories, `_002` through `_010` |
| `rent_burden_30_plus_units` | Rent is at least 30% of income, `_007` through `_010` |
| `rent_burden_50_plus_units` | Rent is at least 50% of income, `_010` |
| `rent_burden_not_computed_units` | Ratio not computed, `_011` |

The 30% and 50% rates divide by the **computable** units, excluding the “not computed” category. The unknown rate divides “not computed” units by total rent-paying units. Raw source strings and all eleven categories are retained locally.

The county source has 1,332 tracts; all 799 Chicago tract IDs match. All acquired count estimates/MOEs were present. Rates are computable for **796 tracts**; three have zero denominators and retain null rates.

Negative Census sentinels, annotations, and nonfinite values become null. Missing components propagate to derived sums. For summed counts, MOE is approximated with the square root of the sum of squared component MOEs, which omits covariance. Rate MOEs are not calculated. These are survey estimates, not individual household records. See [Census ACS guidance](https://www.census.gov/programs-surveys/acs/guidance/handbooks/general.html).

### Housing terms

Census-produced aggregate statistics are US federal government data and generally public domain. Credit the US Census Bureau, ACS 2024 5-year estimates, B25070. The [Census copyright policy](https://www.census.gov/about/policies/copyright.html) is the terms reference; its HTML page returned HTTP 403 from this environment, while the official source file and metadata were accessible.

## Acquire and verify

```bash
# Build the Chicago tract set if needed, after acquiring social vulnerability:
.venv/bin/python scripts/clip_chicago_vulnerability.py

# Fetch both environment/housing sources:
.venv/bin/python scripts/load_chicago_environment.py

# Reproduce normalized data from cached source subsets without network requests:
.venv/bin/python scripts/load_chicago_environment.py --from-cache

.venv/bin/python -m pytest tests/test_environment_enrichment.py -q
.venv/bin/python -m mypy --follow-imports=silent --ignore-missing-imports scripts/load_chicago_environment.py
```

Artifacts in git-ignored `data/enrichment/environment/`:

- `tract_tree_canopy.jsonl`, `tract_housing_burden.jsonl`: normalized Chicago tract snapshots.
- `canopy_raw.json`, `housing_raw.json`: actual county source subsets.
- Canopy layer/item metadata and Census B25070 variable metadata.
- CMAP methodology PDF, preserving the source date documentation.
- `manifest.json`: source URLs, canopy source dates/units/terms status, housing vintage and full bulk-file hash, normalized hashes/counts/null counts, city input hash, and uncertainty policies.

The optional `--load --project YOUR_PROJECT --dataset a4i_climate` appends the two snapshots to new BigQuery tables, `tract_tree_canopy` and `tract_housing_burden`. Existing model/source tables are not replaced. Both tables join on `geo_id`; pick the latest snapshot per tract and avoid summing repeated tract counts after joining grid cells. Acquisition and normalization use standard-library modules; optional BigQuery loading uses the repository's existing `google-cloud-bigquery` dependency.

## Other sources investigated

- [DOE LEAD](https://lead.openei.org/) is a relevant source for actual energy burden. Its public application describes energy data from ACS 2022 Public Use Microdata Samples / 2018–2022 ACS. Public configuration endpoints were accessible, but the application's advertised Illinois downloadable IRA ZIP endpoint (`/downloads/ami-ira/IL`) returned HTTP 404. No LEAD values were fabricated or substituted into this snapshot. A supported export would be needed for reproducible energy-burden acquisition.
- Impervious surface and measured indoor AC availability were not acquired in this step. Canopy coverage and housing cost burden should retain their own meanings.
