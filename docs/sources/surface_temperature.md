# Landsat land surface temperature (multi-summer)

Two BigQuery tables give every grid cell (`grid_cells`, 5,053 cells of ~330 m) a satellite **surface** temperature
signal from 14 clear summer mornings, 2019–2025:

| Table | Rows | Grain |
|---|---|---|
| `a4i_climate.cell_surface_temp_scenes` | 70,742 (66,241 clear) | cell × scene: `lst_f`, `city_mean_lst_f`, `lst_offset_f`, `is_clear`, `water_frac`, `n_pixels`, within-cell SD |
| `a4i_climate.cell_surface_temp` | 5,053 (5,051 with a value) | cell: median `lst_offset_f`, q25/q75/IQR, SD, mean, `n_scenes`, `water_frac`, first/last year |

`lst_offset_f` = cell LST minus that scene's mean over clear, mostly-land cells (°F). Like `grid_cells.offset_f` it is
an **offset**, not a temperature; day-to-day weather cancels and only the spatial pattern remains.

## Source and licence

USGS Landsat 8 and Landsat 9 Collection 2 Level-2 Surface Temperature (band `ST_B10`, with `QA_PIXEL`), read through the
Earth Engine catalogue copies `LANDSAT/LC08/C02/T1_L2` and `LANDSAT/LC09/C02/T1_L2` by BigQuery's
`ST_REGIONSTATS`. Landsat data are **U.S. Government work, public domain** (USGS: no restrictions on use or
redistribution; credit "Landsat imagery courtesy of the U.S. Geological Survey" is requested).

Scale/offset: Kelvin = DN × 0.00341802 + 149.0 (USGS C2 L2). Verified that `ST_REGIONSTATS` returns **raw DN**
(e.g. 47,379 over a Hegewisch cell on 2020-07-05 → 310.9 K → 100.0 °F).

## Scenes used

WRS-2 path 023 / row 031 covers all of Chicago (footprint ~40.7–42.8 N, −89.8 to −86.9), so row 032 is not needed.
All 65 Landsat 8/9 acquisitions of June–August 2019–2025 on that path/row were probed; 14 were kept because ≥ 80 % of a
fixed ~4 % cell sample (223 cells) was cloud-free by `QA_PIXEL`:

| Scene | Date | Clear cells | City mean LST |
|---|---|---|---|
| LC08_023031_20190601 | 2019-06-01 | 5,012 | 95.8 °F |
| LC08_023031_20200705 | 2020-07-05 | 4,975 | 117.9 °F |
| LC08_023031_20210825 | 2021-08-25 | 4,432 | 111.1 °F |
| LC08_023031_20220609 | 2022-06-09 | 4,829 | 90.6 °F |
| LC09_023031_20220617 | 2022-06-17 | 4,904 | 107.8 °F |
| LC09_023031_20220703 | 2022-07-03 | 4,823 | 107.7 °F |
| LC09_023031_20220719 | 2022-07-19 | 4,929 | 112.1 °F |
| LC09_023031_20230620 | 2023-06-20 | 4,116 | 104.5 °F |
| LC09_023031_20230823 | 2023-08-23 | 4,994 | 111.4 °F |
| LC09_023031_20240606 | 2024-06-06 | 4,358 | 95.7 °F |
| LC08_023031_20240614 | 2024-06-14 | 4,826 | 102.8 °F |
| LC09_023031_20240809 | 2024-08-09 | 4,925 | 94.8 °F |
| LC09_023031_20240825 | 2024-08-25 | 4,761 | 103.4 °F |
| LC09_023031_20250609 | 2025-06-09 | 4,357 | 91.1 °F |

The full probe (all 65 dates, clear fractions) is in `data/enrichment/surface_temp/scene_probe.csv` (git-ignored).

## Method

1. Cell polygon = `[lon_i·0.004, (lon_i+1)·0.004] × [lat_i·0.003, (lat_i+1)·0.003]`, the same `FLOOR` mapping as
   `sql/01_grid_cells.sql` (~144 Landsat 30 m pixels per cell).
2. `ST_REGIONSTATS(cell, 'ee://…', 'ST_B10')` and `'QA_PIXEL'` per cell × scene.
3. **Cloud handling, per cell per scene.** A cell is clear only if every pixel's `QA_PIXEL` lies in 21824 (clear land,
   low cloud/shadow/cirrus confidence) … 21952 (clear water). Cloud, dilated cloud, shadow, or medium/high cloud
   confidence move the value outside that range (min < 21824 or max > 21956), so the cell is dropped for that scene.
   This is stricter than the "cold outlier" heuristic and uses USGS's own mask. Water fraction = (mean QA − 21824)/128.
4. Scene mean = mean `lst_f` over clear cells with `water_frac < 0.5`; `lst_offset_f` = cell − scene mean.
5. Per cell: median, quartiles, SD over clear scenes.

Reproduce (repo root; ~3.5 min for the build, ~141k `ST_REGIONSTATS` calls):

```bash
export CLOUDSDK_CONFIG=$PWD/.gcloud
python3 scripts/enrich_surface_temp.py probe     # -> data/enrichment/surface_temp/scenes.json (--min-clear 0.8)
python3 scripts/enrich_surface_temp.py build     # renders sql/enrich_surface_temp.sql, creates both tables
python3 scripts/enrich_surface_temp.py check     # SQL premise check
python3 scripts/enrich_surface_temp.py export && .venv/bin/python scripts/surface_temp_premise.py data/enrichment/surface_temp/premise_join.csv
```

## Results

Cell medians: mean −0.25 °F, SD 5.2 °F, deciles −6.5 … +5.1 °F (extremes −31.7 / +19.6). Median IQR across scenes
2.5 °F. 4,834 cells have ≥ 10 scenes; 39 have < 5 and 2 (lakefront, Near South Side / Loop) have none.
Hottest community areas: West Lawn (+5.7), Clearing, Archer Heights, Gage Park, Brighton Park (dense bungalow + industrial
southwest). Coolest: O'Hare (−8.5, grass between runways), Hegewisch and South Deering (Lake Calumet water), Riverdale,
Hyde Park, the Loop (−5.5, tall-building shade at 10:30). Examples: Stockyards industrial cell +4.8 °F; Kinzie industrial
corridor +1.5; Humboldt Park −5.8; Lincoln Park −7.6; Jackson Park −13.5.

LST correlates with land cover where air temperature does not: corr(LST, OSM building share) 0.51, green share −0.42,
versus −0.03 and −0.11 for the Heat Watch air offset.

### Premise check: does LST track the Heat Watch air offset?

Measured cells (`n_obs ≥ 8`), n = 1,648 (1,206 train / 442 held-out blocks):

| | Pearson | Spearman |
|---|---|---|
| all measured | 0.40 | 0.40 |
| held-out blocks | 0.42 | 0.33 |
| held-out, LST averaged over 3×3 cells | 0.48 | 0.34 |

Calibration fit `offset_f ≈ 0.06 + 0.21 × lst_offset_f`, r² 0.16 (held-out-only fit: slope 0.26, r² 0.18). A 10 °F
hotter surface ≈ 2 °F hotter air.

Held-out r² of linear models trained on non-held-out cells (baseline RMSE 2.40 °F):
LST alone 0.17; LST 5×5 mean 0.20; lat/lon quadratic trend 0.51; **trend + LST 0.56** (RMSE 1.60). Partial correlation of
LST with air offset after removing the trend: 0.25. A lat/lon quadratic explains only 0.26 of LST variance, so LST is
mostly local signal, unlike the air offset. Using only the 10 scenes with ≥ 90 % clear sky changes nothing (r 0.40).

## Caveats

- **Surface ≠ air temperature.** LST is the skin temperature of roofs, pavement and canopy tops; air temperature at
  street level is smoothed by wind and mixing. Expect a damped, noisy relationship (slope ~0.2 here).
- **Time of day.** Landsat overpasses at ~10:30 local (16:35 UTC); Heat Watch was an afternoon campaign. Morning
  shadows make the Loop look cool; afternoon/evening heat retention is not captured.
- **Resolution.** TIRS thermal is acquired at 100 m and resampled to 30 m by USGS; cell means average ~144 resampled
  pixels, so features smaller than ~100 m are blurred.
- **Clouds.** Masking is per cell using `QA_PIXEL`; scenes are 80–99 % clear. Lakefront cells (< 1 km) are clear in only
  72 % of cell-scenes vs 96 % inland (lake-breeze cloud / shoreline QA flags), so their medians rest on fewer, and
  possibly different, days. Use `n_scenes` and the IQR.
- Scene offsets are against a mean over the clear cells of that scene; partly cloudy scenes shift that mean slightly.
- Hot-day scenes have larger spatial spread (2020-07-05 SD 7.3 °F vs 2025-06-09 4.0 °F); medians of offsets are not
  rescaled per scene.
- Water and grass are cool by emissivity and evaporation; O'Hare and Midway are not "cool places to be".
