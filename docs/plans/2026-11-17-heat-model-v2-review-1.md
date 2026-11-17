VERDICT: NEEDS_REVISION

## Summary Assessment

The plan's approach holds up: a view over `site_context`, v2 templates outside the `sql/NN_` glob, the live model evaluated on the same held-out rows, and no promotion. The data claims it relies on match the live tables. It needs revision for five concrete problems: three commands are wrong, an ordering bug would make the console drop "why" reasons in one supported input shape, and the REQ-003 / REQ-012 failure paths are under-specified and untested.

## Critical Issues (must fix)

1. **`bq show` without `--model` fails on a model (Task 1 Step 4, Task 3 Step 3, Task 6 Step 2).** I ran `bq show --format=json a4i_climate.heat_offset_model` and it returns `Not found: Table ...heat_offset_model`. `bq show --model --format=json a4i_climate.heat_offset_model` works (lastModifiedTime today = `1794941957345`). Three steps depend on this command: the REQ-012 record, and the "live model untouched" proof for REQ-013 in Tasks 3 and 6. Fix all three commands.

2. **Task 4: `why_pairs` must normalise first and combine second, not "call `combine_trend` first".** `planner.why_pairs` accepts three input shapes: dicts, flat `[feature, value]` pairs, and nested `[["feature", f], ["contribution_f", v]]` pairs. The interface says `combine_trend` accepts only dicts and flat pairs. If `combine_trend` runs first, a nested item's `item[0]` is `["feature", ...]`, so the reason comes out under that list as its feature name instead of the real one. That would break the console's why chips for the live model too, and no planned test would catch it. Specify `combine_trend(why_pairs(raw))`.
   - `combine_trend` must also skip malformed entries (missing key, non-numeric value) instead of raising. The existing `tests/test_python_tools.py::test_describe_why_orders_and_signs` asserts `describe_why([{"feature": "x"}]) == ""`. Once `describe_why` calls `combine_trend` before slicing, that test fails unless malformed rows are dropped.
   - Add a test for each of these cases: nested pairs through `why_pairs`, and a malformed entry through `combine_trend`.

3. **REQ-003's kill path is under-specified and has no test.**
   - (a) The KILL branch ("retrain with `surface_heat_f` removed") names no template, no model name, and no runner command. It is unclear whether it overwrites `heat_offset_model_v2` or creates e.g. `heat_offset_model_v2_nolst`.
   - (b) For the fallback candidate the spec says "it must beat the previous model". `run_v2.sh evaluate` only checks v2 against trend-only + 0.02, so that rule never runs.
   - (c) The PASS/KILL decision sits in bash parsing of `bq` JSON with no offline test. I checked the output shape: a multi-statement script gives `[[{...}],[{...}]]`, a single statement gives `[{...}]`, and every number comes back as a string (`"1"`). Template `12` has two statements, so the parser has to pick the right result set and cast to float.
   - Fix: put the decision in a small Python function (e.g. `decide(rows, margin=0.02) -> ("PASS"|"KILL", msg)`) with offline tests for pass, kill and fallback. Name the fallback model and how it gets built (a template constant or a second statement in `11`). Add "fallback must beat previous_model" to the check. Add this to Review Focus.

4. **Task 6 Step 3 command cannot run as written.** `scripts/check_tool_sql.py` reads `os.environ["GOOGLE_CLOUD_PROJECT"]`, and this checkout has no `.env` (confirmed). The command needs `GOOGLE_CLOUD_PROJECT=qwiklabs-gcp-04-3e58e01275b8` (and optionally `BQ_LOCATION=US`), or it fails with KeyError even after ADC login.

5. **REQ-012 failure path is missing.** Task 1 says what to do if bucket creation is denied, but not if `EXPORT MODEL` itself fails. Export of a TRANSFORM model depends on every TRANSFORM function being exportable; this one uses `ML.BUCKETIZE` and `LOG`. I did not verify this; it is a live-only fact.
   - Add an explicit "if EXPORT fails: stop, report, do not train" step.
   - The bucket `gs://a4i-qwiklabs-gcp-04-3e58e01275b8/` already exists. Prefer a prefix in it over creating a new bucket, which lab accounts often block.
   - A working BQML copy of the live model already exists at `a4i_climate_backup_20261117_214035.heat_offset_model` (made by the untracked `scripts/backup_bigquery.py`). Record it in the backup note as the real rollback: an exported SavedModel cannot be re-imported as LINEAR_REG with EXPLAIN_PREDICT. The plan's "re-run sql/04 at the recorded commit" restore also assumes `site_context` has not changed since.

## Suggestions (nice to have)

- **Record the spec deviations explicitly** in the plan header or the trace:
  - REQ-001's "Applies when `sql/04` builds" and REQ-002's "`sql/05` runs" are moved to `sql/v2/11` and `sql/v2/12`. This is the right call given REQ-013, but it changes the wording of those requirements.
  - The partial deferrals should be marked "partially deferred to the Layer 2/3 plan", not left implicit: REQ-002's `surface_heat_model` row, REQ-004's labels for `surface_heat_model` features, REQ-010's "when either new layer first ships", and REQ-012's "before `surface_heat_model`".
  - The REQ-006..009 deferral row itself is properly recorded.
- **The spec asks for the old feature decision to be recorded with numbers.** The spec says the existing OSM shares, density and building era "may stay if they do not hurt held-out r2 (builder's call, recorded with numbers)". The plan drops them with no measurement. Add a third candidate (v2 + old physical features) to `11`/`12`, or at least record one held-out number for it in Task 3.
- **REQ-005 coverage:** the docs that Task 3 writes (ARCHITECTURE.md) should also say "surface" for the LST values. Consider extending `test_surface_feature_labelled_as_surface` to the console label `hot surfaces (satellite)`. Note in the trace that the tool-description part of REQ-005 is deferred to promotion.
- **`test_live_model_not_overwritten`: scan raw template text rather than rendered text.** Rendering every `sql/*.sql` with `load_vars("PROJECT","DATASET")` raises KeyError: `02` needs `ACS_TABLE`, and `enrich_surface_temp.sql` needs `SCENE_IDS`, which is not in `chicago.json`. The pattern `heat_offset_model\`` matches the raw `{{PROJECT}}.{{DATASET}}.heat_offset_model\`` text fine.
- **`transform_outputs` parser:** the TRANSFORM list in `sql/04` has commas inside `ML.BUCKETIZE` arrays and several bare columns on one line, so splitting on commas is fragile. Either split on top-level commas, or take `AS (\w+)` plus bare identifiers. The expected live set is in `bq show --model` `transformColumns`: `lake_distance_band, downtown_distance_band, log_pop_density, building_era, building_share, green_share, paved_use_share, log_road_density`. Pinning that set in the test is a good cross-check.
- **Task 5 `tool_sql`:**
  - State the model argument concretely, e.g. `model=build_tools_yaml.tbl("heat_offset_model_v2")`; `MODEL` is a full backticked `${...}` reference.
  - `compare_v2.py` must also run `render_toolbox.resolve()` on the `${GOOGLE_CLOUD_PROJECT}` / `${BQ_DATASET:a4i_climate}` placeholders, which the step does not mention.
  - Prefer `bq query --parameter=limit:INT64:20 ...` over replacing `@limit` etc. in the text.
  - The refactor touches only the shared scoring query, so say whether `table` should also replace the `modelled` CTE's `site_context` in `equity_audit`. It makes no difference (same rows), but the implementer should not have to guess.
- **Promotion note:** the view recomputes a 5053x5053 non-equi neighbour join on every query. That is fine for evaluation. For promotion, list "materialise `site_context_v2` as a table (additive)" among the remaining steps, since four tools would hit it live.
- **Spec "Rigor" step:** `stress-test` before building is not in the plan. `ai-analyst-plus/` exists locally; add a step to Task 2 or Task 3 that does not block progress. Task 5 partly covers `triangulation`; add the community-area check.
- **Review Focus additions:** the bq JSON shape and string numbers (item 3c above); EXPORT failure (item 5); `combine_trend` with nested and malformed input (item 2).

## Verified Claims (things you confirmed are correct)

- Live tables (read-only queries): `site_context` has 5053 rows, 5053 distinct `cell_id`. `cell_surface_temp` has one row per `site_context` cell, with matching `lat_i`/`lon_i`. 2 cells have null `lst_offset_f`. `cell_land_cover` has `impervious_pct_300m` and `tree_canopy_pct_300m` for every cell. There are 442 held-out cells and 1207 training cells (`n_obs >= 8`). The measured offset range is -13.88..+6.71 °F. There are 3404 unmeasured cells. All column names in the plan's Consumes exist.
- The planned 3x3 neighbour mean (`LEFT JOIN ... ABS(lat_i diff) <= 1 AND ABS(lon_i diff) <= 1`, grouped by cell) gives 0 null rows over all 5053 cells (minimum 2 neighbours with values; 609 cells have a partial neighbourhood). Task 3's expected `(5053, 0)` holds, provided the view aggregates before joining (no row duplication).
- A `--dry_run` of the planned v2 `CREATE MODEL` validates: precomputed trend columns, `surface_heat_f`, the NLCD columns and `ML.BUCKETIZE(dist_to_lake_km, ...) AS lake_distance_band` in TRANSFORM, same OPTIONS as `sql/04`, trained from `site_context` + `cell_surface_temp` + `cell_land_cover`. The attribution names will be the TRANSFORM output names.
- `ML.EVALUATE` of the live model on `site_context_v2` held-out rows is valid. The view keeps every raw column the live TRANSFORM needs, and the held-out filter matches `sql/05`, so "previous model" is scored on the same 442 cells, as the spec intends.
- `run_sql.sql_files` uses a non-recursive `SQL_DIR.glob("[0-9][0-9]_*.sql")`, so `sql/v2/*.sql` is not picked up by `make model` and does not break `test_pipeline_files_are_numbered_in_order`.
- Adding the `TREND_*` / `KM_PER_DEG_*` keys to `sql/chicago.json` is safe: `load_vars` just passes them through, and `build_tools_yaml` reads only `MIN_OBS`. `KM_PER_DEG_LON` = 83 matches cos(41.84°) x 111.3.
- `scripts/_env.sh` accepts `PROJECT=` with no `.env`. Following `scripts/enrich_land_cover.sh` (`load_vars`, `render`, `SQL_DIR`, SQL on stdin) is a valid pattern for `run_v2.sh`.
- The console really lacks 3 of the 8 live features (`downtown_distance_band`, `log_pop_density`, `log_road_density`), as the plan says.
- The Global Constraint "no promotion; tools.yaml byte-identical" is consistent with `test_tools_yaml_is_up_to_date`. Baseline `.venv/bin/python -m pytest tests -q` = 169 passed.
- No model-name collision: the dataset already has experiment models `heat_offset_v2` / `heat_offset_v3`, which differ from the plan's `heat_offset_model_v2` and `heat_offset_trend_only`.
