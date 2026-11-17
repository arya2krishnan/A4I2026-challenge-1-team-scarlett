# Heat Model v2 (Layer 1: "how hot it feels") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use 10x-engineer:subagent-driven-development (recommended) or 10x-engineer:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Train and evaluate `heat_offset_model_v2` (location trend + Landsat surface heat + NLCD land cover) beside the live model, with backup, labels, and before/after equity evidence, without promoting it.

**Architecture:** A BigQuery VIEW `site_context_v2` = live `site_context` + trend, smoothed surface-heat and land-cover columns (the live pipeline 01-06 is not edited). New templates in `sql/v2/` train a trend-only baseline and v2, and evaluate both plus the live model on the same held-out superblocks. Python narration and the console's label map learn the v2 feature names; a comparison script renders the existing equity-audit SQL against either model. Everything runs through the `bq` CLI (no application-default credentials on this machine).

**Tech Stack:** BigQuery / BQML LINEAR_REG with TRANSFORM, `bq` CLI, Python 3.11 + pytest + sqlglot, TypeScript (console labels).

**Spec:** `docs/specs/2026-11-17-heat-layers-design.md` (Spec ID `scarlett-heat-three-layers`; Layer 1 approved by the user 2026-11-17: "go ahead with the V2 model").

Paths are relative to the repo root. Work on a new branch `heat-model-v2` cut from `heat-layers-reversibility` (it carries REQ-012/013). Commit per task; **do not push** unless the user asks.

## Global Constraints

- **Do not promote:** `toolbox/build_tools_yaml.py`'s `MODEL` stays `heat_offset_model`; `toolbox/tools.yaml` must be byte-identical after every task (`test_tools_yaml_is_up_to_date`). No redeploy of Toolbox, agent or console.
- Never edit `sql/01..06_*.sql` or recreate `heat_offset_model` / `site_context` (REQ-013).
- Model predicts an OFFSET (°F vs the Chicago average), never a temperature. Race/demographics are never model features.
- Landsat-derived values are labelled "surface" heat, never air temperature (REQ-005).
- Kill margin: v2 held-out r2 must be ≥ trend-only r2 + 0.02 (REQ-003).
- All shell: `bash`, prefix `CLOUDSDK_CONFIG=$PWD/.gcloud PROJECT=qwiklabs-gcp-04-3e58e01275b8` (no `.env` in this checkout; `~/.config/gcloud` is blocked). bq reads SQL from stdin because templates start with `--`.
- Offline tests: `.venv/bin/python -m pytest <file> -q`; full suite `make test`.

## Review Focus

1. **Cells with no surface value** (2 lakefront cells null in `cell_surface_temp`, more with null neighbours): v2 must still score every `site_context` row — `surface_heat_f` falls back to the 3x3 neighbour mean, then 0; the view test and a live null count pin it (Tasks 2, 3).
2. **Unmeasured edge cells** (O'Hare, Riverdale, Hegewisch) where a quadratic trend can run away: the evaluation reports how many unmeasured cells predict outside the measured offset range (−13.9..+6.7 °F) and the top 5 by |offset|; Task 3 records whether a cap is needed.
3. **Attributions arriving as `[feature, value]` pairs through MCP** as well as dicts: `combine_trend` accepts both and the test covers both (Task 4).
4. **A feature name the console has no label for** (today 3 of 8 live features render raw): a test parses every TRANSFORM output of both models and fails on any missing label in either label map (Task 4).
5. **Running a v2 script against the live objects by mistake:** a test asserts no `sql/v2` template creates `heat_offset_model` or `site_context` and that `sql/04` never references v2 columns (Task 2).

## Requirements Trace

| ID | Owning task(s) | Verifying test / evidence still needed |
|---|---|---|
| REQ-001 | 2, 3 | `test_v2_transform_has_required_features`, `test_v2_trains_on_measured_train_cells`; live model exists (Task 3) |
| REQ-002 | 2, 3 | `test_v2_evaluation_reports_four_models`; live evaluation numbers recorded in docs/ARCHITECTURE.md |
| REQ-003 | 3 | live evaluation; `scripts/run_v2.sh evaluate` exits non-zero and prints KILL when margin < 0.02 |
| REQ-004 | 4 | `test_every_model_feature_has_labels`, `test_combine_trend_*` |
| REQ-005 | 4 | `test_surface_feature_labelled_as_surface`; tool descriptions unchanged (no promotion) — recheck at promotion |
| REQ-006, REQ-007, REQ-008, REQ-009 | — | Out of scope: Layers 2/3 get their own plan |
| REQ-010 | 5 | live before/after equity audit + top-20 overlap recorded in docs/ARCHITECTURE.md |
| REQ-011 | 6 | `make test`; tools.yaml stale test; live `scripts/check_tool_sql.py` needs ADC (user runs `gcloud auth application-default login`) |
| REQ-012 | 1 | live `gcloud storage ls` of export path; note in docs/ARCHITECTURE.md |
| REQ-013 | 2 | `test_live_model_not_overwritten` |

---

### Task 1: Back up the live model

**Requirements:** REQ-012

**Files:**
- Create: `scripts/backup_model.sh`
- Modify: `docs/ARCHITECTURE.md` (new "Model backups" subsection under "Verified live")

**Interfaces:**
- Produces: `gs://qwiklabs-gcp-04-3e58e01275b8-model-backups/heat_offset_model/<UTC yyyymmddThhmm>/` and the git commit hash of `sql/04_train_model.sql`.

- [ ] **Step 1: Create branch** `git checkout -b heat-model-v2` (from `heat-layers-reversibility`).
- [ ] **Step 2: Write `scripts/backup_model.sh [model_name]`** (default `heat_offset_model`): sources `scripts/_env.sh`; creates bucket `gs://$PROJECT-model-backups` in `US` if `gcloud storage buckets describe` fails; runs `EXPORT MODEL \`$PROJECT.$BQ_DATASET.<model>\` OPTIONS(URI='gs://…/<model>/<stamp>/')` via `bq query`; prints the URI and `git log -1 --format=%H -- sql/04_train_model.sql`.
- [ ] **Step 3: Run** `CLOUDSDK_CONFIG=$PWD/.gcloud PROJECT=qwiklabs-gcp-04-3e58e01275b8 bash scripts/backup_model.sh`
  Expected: URI printed; `gcloud storage ls <URI>` lists model files. If bucket creation is denied by the lab account, stop and report (do not proceed to training).
- [ ] **Step 4: Record** the URI, commit hash, date and the live model's `lastModifiedTime` (`bq show --format=json a4i_climate.heat_offset_model`) in `docs/ARCHITECTURE.md`, with the restore path: re-run `sql/04` at the recorded commit (deterministic for LINEAR_REG on the same rows); the export is the evidence of what was live.
- [ ] **Step 5: Commit** `git add scripts/backup_model.sh docs/ARCHITECTURE.md && git commit -m "Back up live heat_offset_model before v2 (REQ-012)"`

### Task 2: v2 templates, runner and offline tests

**Requirements:** REQ-001, REQ-002, REQ-013

**Files:**
- Modify: `sql/chicago.json` (add `"TREND_LAT0": 41.84, "TREND_LON0": -87.68, "KM_PER_DEG_LAT": 111.0, "KM_PER_DEG_LON": 83.0`)
- Create: `sql/v2/10_site_context_v2.sql`, `sql/v2/11_train_v2.sql`, `sql/v2/12_evaluate_v2.sql`
- Create: `scripts/run_v2.sh`
- Test: `tests/test_model_v2_sql.py`

**Interfaces:**
- Consumes: tables `site_context`, `cell_surface_temp` (`cell_id, lat_i, lon_i, lst_offset_f`), `cell_land_cover` (`cell_id, impervious_pct_300m, tree_canopy_pct_300m`); `run_sql.load_vars`, `run_sql.render`.
- Produces: VIEW `site_context_v2` = all `site_context` columns + `trend_lat_km, trend_lon_km, trend_lat2, trend_lon2, trend_latlon` (km from (TREND_LAT0, TREND_LON0); squares/product of those), `surface_heat_f` (3x3-neighbour mean of `lst_offset_f` over cells with a value, else 0), `impervious_pct_300m`, `tree_canopy_pct_300m`. Models `heat_offset_trend_only` (TRANSFORM: the five trend columns + `offset_f`) and `heat_offset_model_v2` (TRANSFORM: five trend columns, `surface_heat_f`, `impervious_pct_300m`, `tree_canopy_pct_300m`, `ML.BUCKETIZE(dist_to_lake_km, [0.5,1.0,2.0,4.0,8.0,14.0]) AS lake_distance_band`, `offset_f`); same OPTIONS as `sql/04` (LINEAR_REG, NO_SPLIT, l2_reg 1.0, enable_global_explain). `scripts/run_v2.sh {render <file>|build|evaluate}`.

- [ ] **Step 1: Write failing tests** in `tests/test_model_v2_sql.py` (render with `run_sql.load_vars("PROJECT","DATASET")`):

```python
V2 = sorted((ROOT / "sql" / "v2").glob("*.sql"))
V2_FEATURES = {"trend_lat_km", "trend_lon_km", "trend_lat2", "trend_lon2", "trend_latlon",
               "surface_heat_f", "impervious_pct_300m", "tree_canopy_pct_300m"}

def test_v2_templates_render_and_parse(): ...            # every V2 file renders without "{{" and parses (reuse parseable())
def test_v2_transform_has_required_features():          # 11_train_v2.sql v2 TRANSFORM contains all V2_FEATURES
def test_v2_trains_on_measured_train_cells():           # both CREATE MODEL selects contain "n_obs >= 8", "NOT is_holdout", "offset_f IS NOT NULL"
def test_v2_has_no_demographic_features():               # no "poverty", "vulnerab", "race", "pop_65", "no_vehicle", "income" in 11_train_v2.sql
def test_v2_evaluation_reports_four_models():           # 12 output rows named: baseline_predict_zero, trend_only, previous_model, model_v2
def test_live_model_not_overwritten():
    # only sql/04 creates `...heat_offset_model` (exact, backtick-terminated); no v2 file creates site_context`
    # or heat_offset_model`; sql/04 mentions none of V2_FEATURES
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_model_v2_sql.py -q` → FAIL (files missing).
- [ ] **Step 3: Write the three templates.** `10` = `CREATE OR REPLACE VIEW \`{{PROJECT}}.{{DATASET}}.site_context_v2\``; neighbour mean via join of `cell_surface_temp` on `ABS(n.lat_i - c.lat_i) <= 1 AND ABS(n.lon_i - c.lon_i) <= 1`. `11` = two `CREATE OR REPLACE MODEL` statements (trend-only, v2). `12` = held-out set as in `sql/05` but from `site_context_v2`; rows: zero baseline, `ML.EVALUATE` of each of the three models (live model evaluated on the same rows), plus a second statement: count and top 5 (community_area, predicted_offset_f) of `n_obs IS NULL OR n_obs < {{MIN_OBS}}` cells whose v2 prediction is outside the measured range (`MIN/MAX(offset_f)` over measured cells).
- [ ] **Step 4: Write `scripts/run_v2.sh`** following `scripts/enrich_land_cover.sh` (render via `run_sql`, pipe to `bq` on stdin). `build` runs 10 then 11; `evaluate` runs 12 with `--format=json`, prints a table, and exits 3 printing `KILL: v2 r2 <x> < trend-only <y> + 0.02` when the margin fails, else `PASS`.
- [ ] **Step 5: Run** `.venv/bin/python -m pytest tests/test_model_v2_sql.py tests/test_sql_and_toolbox.py -q` → PASS (tools.yaml unchanged).
- [ ] **Step 6: Commit** the five new files + `sql/chicago.json` + test: `git commit -m "Add v2 heat model templates beside the live model (REQ-001/002/013)"`

### Task 3: Train, evaluate, apply the kill criterion

**Requirements:** REQ-001, REQ-002, REQ-003

**Files:**
- Modify: `docs/ARCHITECTURE.md` (new "Model v2 (candidate, not promoted)" section)

**Interfaces:**
- Consumes: `scripts/run_v2.sh build|evaluate` (Task 2).
- Produces: live `site_context_v2`, `heat_offset_trend_only`, `heat_offset_model_v2`; recorded numbers.

- [ ] **Step 1: Build** `CLOUDSDK_CONFIG=$PWD/.gcloud PROJECT=qwiklabs-gcp-04-3e58e01275b8 bash scripts/run_v2.sh build`
  Expected: view + 2 models created; then `SELECT COUNT(*), COUNTIF(surface_heat_f IS NULL) FROM site_context_v2` = (5053, 0).
- [ ] **Step 2: Evaluate** `… bash scripts/run_v2.sh evaluate`
  Expected (from the premise check, not a guarantee): trend-only r2 ≈ 0.5, v2 ≈ 0.55, previous ≈ 0.26; `PASS`. If it prints `KILL`: stop, retrain with `surface_heat_f` removed as the fallback candidate (spec REQ-003), record both results, and report to the user before Task 5.
- [ ] **Step 3: Record** the four rows (r2, RMSE, MAE, held-out n), the edge-cell count and top 5, and whether a cap is recommended, in `docs/ARCHITECTURE.md`. Also confirm `heat_offset_model` is untouched: its `lastModifiedTime` from `bq show --format=json` equals the value captured in Task 1.
- [ ] **Step 4: Commit** `git commit -m "Record v2 held-out evaluation (REQ-002/003)" docs/ARCHITECTURE.md`

### Task 4: Feature labels in the agent and the console

**Requirements:** REQ-004, REQ-005

**Files:**
- Modify: `agent/heat_dispatch/narration.py` (labels + `combine_trend`)
- Modify: `agent/heat_dispatch/planner.py:145` (`why_pairs` calls `combine_trend` first)
- Modify: `web/frontend/src/format.ts:9-13` (`FEATURE_LABEL`)
- Test: `tests/test_feature_labels.py`

**Interfaces:**
- Produces: `narration.combine_trend(why: list) -> list[dict]` — accepts `{feature, contribution_f}` dicts or `[feature, value]` pairs; sums every feature starting with `trend_` into one `{"feature": "location_trend", "contribution_f": <sum>}`; keeps others; returns dicts sorted by `abs(contribution_f)` desc. `describe_why` calls it before slicing `top`.
- Labels (both maps; Python wording first, console short form second): `location_trend` → "location in the city (lake-to-southwest gradient)" / "location in city"; `surface_heat_f` → "surface heat measured by satellite" / "hot surfaces (satellite)"; `impervious_pct_300m` → "pavement and roofs nearby" / "pavement"; `tree_canopy_pct_300m` → "tree canopy nearby" / "tree canopy". Console map also gains the three live features it lacks today: `downtown_distance_band` "distance to Loop", `log_pop_density` "density", `log_road_density` "streets".

- [ ] **Step 1: Write failing tests:**

```python
def transform_outputs(path) -> set[str]:  # names after "AS" (or bare column) inside TRANSFORM(...), minus offset_f
def test_every_model_feature_has_labels():
    feats = transform_outputs("sql/04_train_model.sql") | transform_outputs("sql/v2/11_train_v2.sql")
    feats = {f for f in feats if not f.startswith("trend_")} | {"location_trend"}
    ts = (ROOT / "web/frontend/src/format.ts").read_text()
    for f in feats:
        assert f in narration.FEATURE_LABELS
        assert re.search(rf"\b{f}\s*:", ts)
def test_combine_trend_sums_dicts():
    out = narration.combine_trend([{"feature": "trend_lat_km", "contribution_f": 1.0},
                                   {"feature": "trend_lon2", "contribution_f": 0.5},
                                   {"feature": "surface_heat_f", "contribution_f": -2.0}])
    assert out == [{"feature": "surface_heat_f", "contribution_f": -2.0},
                   {"feature": "location_trend", "contribution_f": 1.5}]
def test_combine_trend_accepts_mcp_pairs():
    assert narration.combine_trend([["trend_lat_km", 0.4], ["trend_latlon", 0.1]]) == \
        [{"feature": "location_trend", "contribution_f": 0.5}]
def test_surface_feature_labelled_as_surface():
    assert "surface" in narration.label_for("surface_heat_f")
    assert "air" not in narration.label_for("surface_heat_f")
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_feature_labels.py -q` → FAIL.
- [ ] **Step 3: Implement** labels, `combine_trend`, the `describe_why` and `why_pairs` calls, and the `format.ts` entries.
- [ ] **Step 4: Run** `make test` → all pass (existing narration tests unchanged; frontend tests run only if `web/frontend/node_modules` exists — if so `make test-web` must pass too).
- [ ] **Step 5: Commit** the four files: `git commit -m "Label v2 features; combine trend terms into one reason (REQ-004/005)"`

### Task 5: Before/after equity audit and top-20 comparison

**Requirements:** REQ-010

**Files:**
- Modify: `toolbox/build_tools_yaml.py` (factor `SCORED_SITES` into `scored_sites(model: str = MODEL, table: str = "site_context") -> str`; `SCORED_SITES = scored_sites()`; expose `tool_sql(name: str, model: str = MODEL, table: str = "site_context") -> str` returning that tool's statement)
- Create: `scripts/compare_v2.py`
- Modify: `docs/ARCHITECTURE.md`
- Test: `tests/test_sql_and_toolbox.py` (add one test)

**Interfaces:**
- Consumes: `build_tools_yaml.tool_sql`, the live v2 objects (Task 3).
- Produces: `scripts/compare_v2.py --limit 20 --heat-weight 0.5` printing equity rows for both models and top-N overlap.

- [ ] **Step 1: Write failing test** `test_tool_sql_can_target_v2_without_changing_yaml`: `tool_sql("equity_audit", model=<v2 ref>, table="site_context_v2")` contains `heat_offset_model_v2` and `site_context_v2`; default `tool_sql("equity_audit")` contains neither; `test_tools_yaml_is_up_to_date` still passes.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_sql_and_toolbox.py -q` → FAIL.
- [ ] **Step 3: Implement** the refactor.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_sql_and_toolbox.py -q` → PASS.
- [ ] **Step 5: Write `scripts/compare_v2.py`**: substitutes `@limit/@heat_weight/@min_density/@spacing_cells/@min_offset` with the tool defaults from `tools.yaml` (`--limit 20 --heat-weight 0.5` overrideable), runs `equity_audit` and `rank_priority_sites` for live and v2 via `bq query --format=json` (stdin), prints: both audit rows side by side; change in share of sites in the top vulnerability quartile, in points; top-20 cell overlap and community areas entering/leaving. Flags (prints, does not block) a drop > 10 points — the team's blocking decision is still open.
- [ ] **Step 6: Run** `CLOUDSDK_CONFIG=$PWD/.gcloud PROJECT=qwiklabs-gcp-04-3e58e01275b8 .venv/bin/python scripts/compare_v2.py` → both audits print. Record the numbers and the area shifts in `docs/ARCHITECTURE.md`.
- [ ] **Step 7: Commit** the three files + test: `git commit -m "Compare live vs v2: equity audit and top-20 overlap (REQ-010)"`

### Task 6: Final verification and handoff

**Requirements:** REQ-011

**Files:** none new.

- [ ] **Step 1:** `make test` → all pass; `git diff main -- toolbox/tools.yaml` → empty.
- [ ] **Step 2:** `bq show` shows `heat_offset_model` lastModified unchanged since Task 1.
- [ ] **Step 3:** Live tool check: ask the user to run `! CLOUDSDK_CONFIG=$PWD/.gcloud gcloud auth application-default login`, then `CLOUDSDK_CONFIG=$PWD/.gcloud .venv/bin/python scripts/check_tool_sql.py` → exit 0. If ADC is still missing, report REQ-011's live check as not yet run.
- [ ] **Step 4:** Report to the user: evaluation table, PASS/KILL, edge cells, equity before/after, and the promotion steps left (switch `MODEL` + `site_context_v2` in `build_tools_yaml.py`, `top_k_features` → all + trend summing in tool SQL, retune cutoff range, regenerate yaml, redeploy) — none performed.
