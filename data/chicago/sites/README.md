# data/chicago/sites/: where people in Chicago can go to cool down

Point-in-time snapshots of **official City of Chicago open data** about places that serve, or could
serve, as heat-relief sites. Every file here was written by [`tools/fetch_chicago_sites.py`](../../../tools/fetch_chicago_sites.py),
run by the GitHub Actions workflow [`fetch-chicago-sites.yml`](../../../.github/workflows/fetch-chicago-sites.yml)
directly against `data.cityofchicago.org`. Nothing was typed, edited or geocoded by hand.

- **Retrieved:** see `retrieved_at` in [`manifest.json`](manifest.json) and in every row (UTC).
- **Integrity:** `manifest.json` records row counts and a SHA-256 for each CSV.
- **Licence / terms:** [City of Chicago Data Portal Terms of Use](https://www.chicago.gov/city/en/narr/foia/data_disclaimer.html).
  The portal lists no formal licence for these datasets. Cite the City as the source.
- **Refresh:** `python tools/fetch_chicago_sites.py` (stdlib only), or push a change to the tool on a
  non-main branch and the workflow re-fetches and commits. Then reload BigQuery (below).

## Files

| File | Rows* | Source (Socrata id) | What it is |
|---|---|---|---|
| `cooling_centers.csv` | 287 | [Cooling Centers `msrk-w9ih`](https://data.cityofchicago.org/d/msrk-w9ih) (DFSS) | **The City's official cooling network.** 79 libraries, 43 air-conditioned Park District facilities, 110 splash pads (spray features), 22 police districts, 14 satellite + 6 regional senior centers, 7 City Colleges, 6 community service centers. |
| `libraries.csv` | 82 | [Libraries `x8fc-8rcq`](https://data.cityofchicago.org/d/x8fc-8rcq) (CPL) | Every Chicago Public Library branch with **weekly service hours**. Use it for the 📚 extended-hours intervention: who closes at 5 vs 8 pm. |
| `police_stations.csv` | 23 | [Police Stations `z8bn-74gv`](https://data.cityofchicago.org/d/z8bn-74gv) (CPD) | 22 district stations (open **24/7** for heat relief and shelter referral) plus CPD Headquarters (not a cooling site). |
| `senior_centers.csv` | 21 | [Senior Centers `qhfc-4cw2`](https://data.cityofchicago.org/d/qhfc-4cw2) (DFSS) | 6 regional + 15 satellite senior centers, weekday hours. |
| `cps_schools.csv` | 645 | [CPS School Locations SY2526 `pb6d-zzuh`](https://data.cityofchicago.org/d/pb6d-zzuh) | All CPS school buildings (`grade_cat` ES = 475, HS = 170). **Not cooling sites today**; see caveats. |
| `candidate_sites.csv` | 457 | derived | One tidy table for the agent: all 287 current cooling sites (`is_current_cooling_site = true`) + 170 CPS high schools as expansion candidates (`false`). |
| `bq_schemas/*.json` | | generated | BigQuery schema per CSV (zip/phone/ids stay STRING so leading zeros survive). |

\*Counts as of the snapshot in `manifest.json`; the portal changes over time.

### Added columns (not in the source data)
- `latitude`, `longitude`: WGS84, taken from the dataset's own point geometry (as geocoded by the City), 7 decimals.
- `in_chicago_bbox`: sanity flag (41.60–42.05 N, −87.95 to −87.50 W). It's `true` for every row in this snapshot.
- `indoor_air_conditioned` (cooling_centers, candidate_sites): `false` only for *Park District Spray Feature*
  (outdoor splash pads). The City states that only the Park District facilities listed in this dataset have
  air conditioning ([Cooling Areas page](https://www.chicago.gov/city/en/depts/fss/provdrs/serv/svcs/dfss_cooling_centers.html)),
  so the 43 *Park District Facility* rows are marked `true`. Blank for CPS schools (unknown).
- `open_24_7` (candidate_sites): `true` for police districts only.
- `is_high_school` (cps_schools): `grade_cat == "HS"`.
- `source_dataset_id`, `retrieved_at`: provenance on every row.
- Socrata bookkeeping columns (`:@computed_region_*`) and raw geometry objects are dropped. All other source
  columns are kept as published, with whitespace collapsed.

## How Chicago actually runs heat relief (context for these files)
- When it's 90°F or hotter, DFSS opens cooling areas at its **six community service centers**, weekdays 9–5. Garfield (10 S. Kedzie) also does 24/7 shelter placement.
- During normal hours people can also cool off at **libraries, air-conditioned Park District fieldhouses,
  senior centers and City College campuses**. Splash pads and pools add outdoor relief.
- **Police district stations stay open 24 hours** for heat relief and shelter referral. They're the only all-night option.
- The City's own count is about 287 cooling facilities, which matches `cooling_centers.csv`. Advocates have pushed
  for more evening/overnight cooling. That's why the hours fields matter for our dispatch logic.

## Caveats (read before using)
1. **Snapshot, not live.** Hours and holiday closures change. Hours are free text (e.g. `"M-F 8am-8pm; Sat 9am-3pm; Closed Sun; Holiday Closures: ..."`), not structured.
2. **Lists differ slightly.** `libraries.csv` has 82 rows but only 79 libraries are in the cooling list.
   At the snapshot, Galewood-Mont Clare is "Closed until further notice". The same goes for senior centers: 21 in `senior_centers.csv`, 20 in the cooling list.
   Treat `cooling_centers.csv` as the authority on what's *in the network*. Use the others for extra attributes (hours, email, district).
3. **CPS high schools are candidates, not cooling sites.** Chicago's heat plan doesn't list schools.
   The CPS dataset doesn't say which buildings have air-conditioned gyms, and summer access depends on staffing and
   summer programming. `grade_cat = HS` **includes charter and contract high schools** (e.g. `NOBLE - ...`), which
   are publicly funded but privately operated, not City-owned buildings. Filter or label them if your pitch says "city-owned".
4. **Park District facilities outside this list** (fieldhouses without AC) are intentionally not included.
5. Existing `scripts/load_chicago_facilities.py` loads the same `msrk-w9ih` dataset but marks *Park District
   Facility* as **not** indoor. The City's note above suggests these 43 sites are air-conditioned. That's worth a
   team decision. This folder doesn't change that script.

## Load into BigQuery

```bash
bash tools/load_chicago_sites_bq.sh                 # uses GOOGLE_CLOUD_PROJECT / BQ_DATASET (default a4i_climate) from .env
bash tools/load_chicago_sites_bq.sh my-project my_dataset
```
Creates/replaces one table per CSV, named `chi_site_<file>` (e.g. `chi_site_candidate_sites`). Example:

```sql
-- Hot tracts with no indoor, air-conditioned cooling site within 800 m (~10 blocks)
SELECT t.geoid
FROM `PROJECT.DATASET.your_tract_table` t
WHERE NOT EXISTS (
  SELECT 1 FROM `PROJECT.DATASET.chi_site_candidate_sites` s
  WHERE s.is_current_cooling_site AND s.indoor_air_conditioned
    AND ST_DWITHIN(ST_GEOGPOINT(s.longitude, s.latitude), ST_GEOGPOINT(t.clon, t.clat), 800));
```

Or a single file without the script:
```bash
bq load --replace --source_format=CSV --skip_leading_rows=1 --allow_quoted_newlines \
  PROJECT:DATASET.chi_site_cooling_centers data/chicago/sites/cooling_centers.csv data/chicago/sites/bq_schemas/cooling_centers.json
```
