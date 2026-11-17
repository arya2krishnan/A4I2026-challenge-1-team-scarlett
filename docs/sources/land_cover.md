# Per-cell land cover: NLCD 2021 imperviousness and tree canopy

## Why

The heat model needs physical features a city can change, so `ML.EXPLAIN_PREDICT` can say whether a block is
hot because of pavement or because it lacks trees. The OSM shares in `grid_cells` are noisy (centroid counting,
uneven mapping). NLCD rasters cover every 30 m pixel uniformly.

## Sources and terms

| Column | Earth Engine asset | Band | Vintage |
|---|---|---|---|
| `impervious_pct`, `impervious_pct_300m` | `USGS/NLCD_RELEASES/2021_REL/NLCD/2021` | `impervious` | 2021 |
| `tree_canopy_pct`, `tree_canopy_pct_300m` | `USGS/NLCD_RELEASES/2021_REL/TCC/v2021-4/TCC_v2021-4_CONUS_2021` | `NLCD_Percent_Tree_Canopy_Cover` | 2021 |

- NLCD 2021 percent developed imperviousness: USGS / MRLC. Catalog:
  <https://developers.google.com/earth-engine/datasets/catalog/USGS_NLCD_RELEASES_2021_REL_NLCD>
- Tree Canopy Cover v2021-4 (NLCD product): USDA Forest Service, distributed through MRLC/NLCD. Catalog:
  <https://developers.google.com/earth-engine/datasets/catalog/USGS_NLCD_RELEASES_2021_REL_TCC_v2021-4>;
  methods: <https://data.fs.usda.gov/geodata/rastergateway/treecanopycover/docs/TCC_v2021-4_Methods.pdf>

Both are US federal government data, **public domain**. Credit USGS NLCD and USDA Forest Service TCC.

The TCC collection only exposes per-year/per-area images. The image id was not documented in the catalog
(Earth Engine asset listing needs a project registered with Earth Engine, which this lab project is not). It was found
by probing names with `ST_REGIONSTATS`; the naming pattern is `TCC_<version>_CONUS_<year>`. The same pattern works
for the deprecated v2023-5 (`USGS/NLCD_RELEASES/2023_REL/TCC/v2023-5/TCC_v2023-5_CONUS_2021`) and for the current
successor (`projects/gtac-data-publish/assets/TCC/Product_Version/2025-6/TCC_v2025-6_CONUS_2021`, newer years
available). We used v2021-4 to match the NLCD 2021 release; on one test polygon the three versions read 2.07, 2.06
and 2.83%.

## Method

`sql/enrich_land_cover.sql` builds `a4i_climate.cell_land_cover` with BigQuery `ST_REGIONSTATS`. The raster is
read in Earth Engine, nothing is downloaded. For each `grid_cells` row:

- **cell**: the cell rectangle, `[lat_i, lat_i+1) x LAT_STEP` by `[lon_i, lon_i+1) x LON_STEP` (the same flooring
  as `sql/01_grid_cells.sql`, about 330 m x 333 m, 0.11 km2);
- **300m**: a disc of `OSM_RADIUS_M` (300 m) around the cell centre, the radius the OSM features use.

Values are area-weighted pixel means (0-100). `*_px` columns are the area-weighted count of valid pixels
(about 146 per cell, 350 per disc). Plus `source_impervious`, `source_canopy`, `vintage` (2021),
`buffer_radius_m`, `computed_at`.

```bash
CLOUDSDK_CONFIG=$PWD/.gcloud bash scripts/enrich_land_cover.sh            # ~20 s for 5,053 cells
CLOUDSDK_CONFIG=$PWD/.gcloud bash scripts/enrich_land_cover.sh --render   # print the SQL only
```

Needs `grid_cells` and the Earth Engine API enabled. `PROJECT` comes from `.env` (or `PROJECT=... bash ...`).
Rebuild after `grid_cells` changes. It does not modify `grid_cells`, the model, or the agent.

## Result (2026-11-17)

5,053 rows, one per grid cell, no nulls, no masked pixels.

| Column | min | median | max | mean |
|---|---|---|---|---|
| `impervious_pct` | 0.0 | 70.1 | 97.6 | 66.7 |
| `tree_canopy_pct` | 0.0 | 5.1 | 78.2 | 6.9 |
| `impervious_pct_300m` | 0.0 | 69.8 | 97.6 | 66.7 |
| `tree_canopy_pct_300m` | 0.0 | 5.3 | 72.5 | 6.9 |

Spot checks: Loop at State/Madison 93.5% impervious, 0.6% canopy; Jackson Park 15.9% / 26.8%; Englewood at
63rd/Halsted 80.4% / 1.3%. On measured training cells (`n_obs >= 8 AND NOT is_holdout`, n = 1,207), Pearson r
with `offset_f` is +0.13 (impervious) and -0.11 (canopy); the 300 m versions are +0.12 / -0.10. That beats the OSM
shares (green -0.08, building -0.05, paved +0.04) but is still weak on its own. Impervious and canopy correlate at
-0.77, so do not read their separate attributions as independent.

## Caveats

- **Resolution:** 30 m pixels averaged over a 330 m cell. That is fine for a block-scale average, not for a
  single street or sidewalk.
- **Canopy is underestimated in cities.** NLCD TCC is a Landsat model and misses street trees and small
  crowns. The citywide cell median is 5%, but high-resolution studies (for example CMAP/Ecopia 2023, in
  `docs/sources/environment.md`) put Chicago canopy in the mid-teens. Use it as a relative ranking, not as an
  absolute canopy figure.
- **Water reads 0** for both layers (not masked). Lakefront and river cells therefore look like they have low
  pavement and no trees; `dist_to_lake_km` already carries the lake effect.
- **Vintage:** both layers are 2021. `heat_observations.observed_at` is empty, so the alignment with the Heat Watch
  campaign year was not checked. Recent planting or construction is not reflected.
