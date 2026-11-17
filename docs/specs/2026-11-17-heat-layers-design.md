# Shared heat base: three layers (why / how hot / how often)

**Invariant format:** tenx/v1

**Spec ID:** scarlett-heat-three-layers

**Status:** draft for approval, 2026-11-17

## Intent

Team Scarlett's agent answers the Today question (hydration trucks, wellness checks, library hours). The team is
widening it into one planning assistant that also serves the budget-cycle question (three permanent cooling centers)
and the decade question (tree planting or cool pavement per dollar). All three need a shared heat base that says, per
~330 m grid cell: how hot it feels relative to the city, how often it gets dangerously hot, and why it is hot in terms
a city can change. Today's base cannot: it learns from one volunteer-driven afternoon (Heat Watch), its held-out r2 is
0.26, and its land-cover features explain almost nothing, so `ML.EXPLAIN_PREDICT` cannot point at a fix.

This is a hackathon project on the existing Qwiklabs project (`a4i_climate`); no new GCP projects or long-lived infra.
This spec covers the shared base plus the immediate Today upgrade. The budget-cycle tool (site selection, cost, what
it displaces) and the decade tool (relief per dollar) are separate follow-on projects that consume these layers.

## Evidence this design rests on (measured 2026-11-17)

New BigQuery tables, built via `ST_REGIONSTATS` on Earth Engine assets (scripts in `sql/enrich_*.sql`):
`cell_land_cover` (NLCD 2021 impervious and tree canopy, cell and 300 m disc) and `cell_surface_temp` /
`cell_surface_temp_scenes` (14 clear Landsat 8/9 summer scenes 2019-2025, QA_PIXEL-masked, per-cell surface
temperature offset). Held-out results on Heat Watch air offsets (442 held-out cells; baseline RMSE 2.40 F):

| Model of the air offset | Held-out r2 |
|---|---|
| Current BQML model (physical features) | 0.26 |
| Surface temperature (LST) alone | 0.17 |
| Lat/lon quadratic trend alone | 0.51 |
| Trend + LST | 0.56 (RMSE 1.60) |

LST correlates 0.51 with building cover and -0.42 with green space (air offset: -0.03 and -0.11); lat/lon explains
only 0.26 of LST. Conclusion: LST is a strong, citywide, multi-year "why" layer for surface heat but a weak direct proxy
for felt air temperature (10 F of surface heat is about 2 F of air). NLCD impervious and canopy correlate -0.77.
Stations: `station_daily_temps`, 13 stations, 2019-01-01..2025-12-31, daily max.

## Approaches considered

- **A. Better features only.** Keep the Heat Watch label, add NLCD impervious/canopy. Smallest change, but land cover
  alone explains ~2% of the air offset; accuracy barely moves and the base is still one afternoon.
- **B. LST as an extra input to the air model only.** Large accuracy gain, but explanations collapse to "hot because
  the satellite says hot", which tells the decade user nothing to change.
- **C. Two-stage (chosen).** A "why" model explains LST from changeable features across many summers and every block;
  a "how hot" model explains the Heat Watch air offset from location trend + LST + land cover; stations supply "how
  often". Each user gets the layer whose data suits them. Chosen by the team, with a quick win first (the "how hot"
  model replaces the current model immediately, improving Today before the other layers exist).
- **Decision: keep the lat/lon trend in the "how hot" model** (team decision, 2026-11-17). Cost accepted: Today's
  explanations often cite location in the city rather than a changeable cause; changeable causes come from the "why"
  layer. This closes the open decision noted in CLAUDE.md.

## Design

### Layer 1: How hot it feels (quick win; replaces `heat_offset_model`)

- **Candidate, then promote (builder-check call).** The deployed Toolbox calls `heat_offset_model` live, so the new
  model is trained as `heat_offset_model_v2` (and its inputs in a new/extended table) without touching the live model.
  The previous model stays as the comparison baseline. Promotion = the model name in `toolbox/build_tools_yaml.py`
  becomes a constant switched to v2 only after REQ-003 and REQ-010 pass; redeploying stays the team's call.
- **Reversibility.** BigQuery has no undo for models (`CREATE OR REPLACE MODEL` overwrites; table time travel does not
  cover models). So: (1) before any training, export the current `heat_offset_model` to Cloud Storage with
  `EXPORT MODEL` and record the path and the git commit of `sql/04_train_model.sql` that built it; (2) the existing
  `sql/04_train_model.sql` is never edited to produce v2 (v2 has its own template or model-name constant), so
  `make model` cannot overwrite the live model; (3) `grid_cells` / `site_context` changes are additive only (new
  columns), so the previous model keeps scoring; (4) narration keeps labels for the previous model's features, so the
  agent works with either model and rollback needs no agent redeploy. Rollback = switch the model-name constant back,
  regenerate `tools.yaml`, and route the Toolbox Cloud Run service to its previous revision.
- **Attributions:** request attributions for all features (not `top_k_features => 3`), sum the trend terms into one
  "location in the city" item, then take the top reasons; otherwise five trend terms can crowd out every other reason.
- **Edges:** check predictions on cells outside the measured footprint (far south, Hegewisch, O'Hare) for quadratic
  blow-up and cap or flag them; record what was done.

- `sql/01_grid_cells.sql` (or `03_site_context.sql`) joins `cell_land_cover` and `cell_surface_temp` onto each cell so
  `site_context` carries `lst_offset_f` (plus a 3x3-neighbourhood mean, which measured better: held-out Pearson 0.48 vs
  0.42), `impervious_pct_300m`, `tree_canopy_pct_300m`. Cells with null LST (2 lakefront cells) get a documented
  fallback (builder's call: neighbourhood mean or 0).
- `sql/04_train_model.sql`: same BQML LINEAR_REG, same label (`offset_f`), same training rows (measured, not held out).
  Features: centred lat/lon quadratic trend, smoothed LST offset, NLCD impervious and canopy (300 m), lake distance
  band. Existing OSM shares, density and building era may stay if they do not hurt held-out r2 (builder's call,
  recorded with numbers).
- `sql/05_evaluate.sql` reports held-out r2/RMSE for: always-zero, trend-only, previous model, new model.
- Toolbox: `toolbox/build_tools_yaml.py` scoring CTE and tool descriptions updated for the new features; regenerate
  `toolbox/tools.yaml`. Agent: `agent/heat_dispatch/narration.py` labels every new feature in plain words; the trend
  terms are narrated as one reason ("location in the city: the lake-to-southwest gradient").

### Layer 2: Why it is hot (new model; serves the decade tool)

- New BQML model `surface_heat_model`: label `lst_offset_f` (median across scenes) for all cells with enough clear
  scenes; spatial superblock hold-out reusing `is_holdout`. Features split into **changeable** (impervious, canopy,
  OSM building share, road density, green share) and **fixed** (lake distance, location trend). Evaluated like Layer 1.
- Output per cell (table `cell_heat_drivers`, refreshed by the pipeline): predicted surface offset, the summed warming
  attribution (F) of the **pavement group** (impervious, road density, building share) and of the **canopy group**
  (tree canopy, green share), and a lever label: `pavement` or `canopy` for whichever group adds more warming, or
  `none` when neither group warms the cell (already cool for changeable reasons). Groups are compared rather than
  single features because impervious and canopy correlate -0.77, which makes single-feature credit unstable.
- Ship bar for Layer 2: changeable features must add at least 0.05 held-out r2 over location-trend-only on the surface
  offset; otherwise `cell_heat_drivers` is not published and the team is told. Attributions are associations; the data cannot
  simulate the effect of a fix, and every consumer must say so.

### Layer 3: How often (serves the budget tool)

- Table `cell_heat_frequency`: per cell, expected dangerous-heat days per summer (Jun-Sep), 2019-2025, computed as the
  count of days where a city reference daily max plus the cell's Layer-1 air offset reaches a threshold (default 95 F,
  parameterised), averaged over the seven summers, with the per-year range. Reference series: builder's call between
  the in-city stations (if any) and the mean of nearest stations, documented with the station list. Heat index is out
  of scope here (stations carry no humidity).

### Rigor (ai-analyst-plus skills, run at fixed points)

- The skills live in `ai-analyst-plus/.claude/skills/` (git-ignored local copy). They are methods, not installed
  tools: the builder reads each SKILL.md and performs it as a written step with the pass/fail thresholds in this spec.
  They do not block progress.
- Before building: `stress-test` on this plan (baselines, leakage, kill criteria).
- Metric definition: `metric-spec` for "dangerous-heat days" and the lever label.
- After each layer: `triangulation` (old vs new top-20 Today sites, Simpson-style checks by community area) and
  `guardrails` (equity audit outcomes as guardrail metrics; a model that improves r2 but shifts priority away from
  high-vulnerability tracts is flagged, not shipped silently).

## Requirements

### REQ-001: How-hot model uses trend, surface temperature and land cover

**Applies when:** `sql/04_train_model.sql` builds `heat_offset_model`.

**Obligation:** The model MUST include a lat/lon trend, a surface-temperature offset feature from `cell_surface_temp`, and NLCD impervious and canopy features from `cell_land_cover`, and MUST be trained only on measured cells outside the held-out superblocks.

**Acceptance criteria:** The rendered `CREATE MODEL` lists those features in its TRANSFORM; its training query filters `n_obs >= MIN_OBS AND NOT is_holdout`; no demographic or race column is a feature.

**Verification needs:** Source inspection of `sql/04_train_model.sql`; an offline test asserting the feature list and filters.

### REQ-002: Held-out comparison against baselines

**Applies when:** `sql/05_evaluate.sql` runs after training either model.

**Obligation:** Evaluation MUST report held-out r2 and RMSE for always-zero, trend-only, the previous physical-feature model, and the new model.

**Acceptance criteria:** One result set with those four rows for the how-hot model (and the equivalent for `surface_heat_model`), computed only on `is_holdout` cells.

**Verification needs:** Live run of `make model`; numbers recorded in docs/ARCHITECTURE.md.

### REQ-003: Kill criterion for the how-hot model

**Applies when:** The new how-hot model is evaluated on held-out cells.

**Obligation:** The new model MUST NOT replace the previous one unless its held-out r2 is at least 0.02 above trend-only; otherwise the team MUST be told, and trend + land cover (without LST) becomes the Layer-1 candidate, evaluated against the same bar's spirit (it must beat the previous model). Layers 2 and 3 proceed using whichever Layer-1 model is promoted.

**Acceptance criteria:** Recorded held-out r2(new) - r2(trend-only) >= 0.02 before the toolbox is regenerated against the new model.

**Verification needs:** Live evaluation output.

### REQ-004: Every model feature has plain-language narration

**Applies when:** The agent narrates `ML.EXPLAIN_PREDICT` attributions for either model.

**Obligation:** Every feature of both models MUST map to a plain-language label, and the trend terms MUST be presented as one combined "location in the city" reason.

**Acceptance criteria:** `narration.py` has a label for every TRANSFORM output of both models; a test fails if a feature lacks a label; trend attributions are summed into one item before display.

**Verification needs:** Offline test comparing model feature names (parsed from the SQL) to narration labels.

### REQ-005: Surface temperature is never presented as air temperature

**Applies when:** Any tool, narration or doc reports a value derived from Landsat.

**Obligation:** Landsat-derived values MUST be labelled as surface temperature, and only Layer-1 predictions MAY be presented as air-temperature offsets.

**Acceptance criteria:** Tool descriptions, narration labels and docs use "surface" for LST values; no output adds an LST offset to an air forecast.

**Verification needs:** Source inspection of tools.yaml descriptions, narration and prompts; an offline string test.

### REQ-006: Why-it-is-hot model with spatial hold-out

**Applies when:** The pipeline builds `surface_heat_model`.

**Obligation:** A BQML model MUST predict the per-cell surface offset from changeable and fixed features, evaluated on held-out superblocks.

**Acceptance criteria:** Model exists; evaluation reports held-out r2/RMSE versus always-zero and location-trend-only; changeable and fixed features are distinguishable by name.

**Verification needs:** Live `make model` run; offline test of the SQL template.

### REQ-007: Per-cell driver and lever label

**Applies when:** `cell_heat_drivers` is built.

**Obligation:** Each cell with a surface value MUST carry the summed warming attribution of the pavement group and of the canopy group, in F, and a lever label of `pavement`, `canopy` or `none`.

**Acceptance criteria:** Row count equals cells with non-null `lst_offset_f`; lever is non-null for every row; `none` exactly when neither group's summed attribution is positive; the rule is documented in the SQL and in the metric spec.

**Verification needs:** Live query of row counts and null counts; source inspection of the label rule.

### REQ-008: Consumers state that fixes are not simulated

**Applies when:** Any tool or narration presents a driver or lever.

**Obligation:** The output MUST state that the attribution identifies a likely cause and cannot predict the temperature after an intervention.

**Acceptance criteria:** Tool description and agent prompt contain that limit; a test checks the phrase is present.

**Verification needs:** Offline test on prompts and tool descriptions.

### REQ-009: Dangerous-heat days per cell

**Applies when:** `cell_heat_frequency` is built.

**Obligation:** Each cell MUST carry expected days per summer at or above a parameterised threshold (default 95 F) for 2019-2025, with the per-year minimum and maximum, from station daily maxima plus the Layer-1 offset.

**Acceptance criteria:** One row per city cell; threshold is a template constant; the reference stations are listed in the doc; values are monotone non-increasing as the threshold rises.

**Verification needs:** Live query; offline test of the template; a check that raising the threshold never increases days.

### REQ-010: Equity audit before and after

**Applies when:** The how-hot model is replaced, and when either new layer first ships.

**Obligation:** The equity audit MUST be run on the previous and new outputs and the change reported with numbers.

**Acceptance criteria:** docs/ARCHITECTURE.md records before/after audit figures for the Today ranking; any shift of priority away from high-vulnerability tracts is called out.

**Verification needs:** Live `equity_audit` tool runs on both models.

### REQ-011: Tools, tests and live checks stay green

**Applies when:** Any layer is merged.

**Obligation:** `toolbox/tools.yaml` MUST be regenerated, `make test` MUST pass, and `scripts/check_tool_sql.py` MUST run every tool against live BigQuery without error.

**Acceptance criteria:** Stale-yaml test passes; offline suite passes; live check exits 0.

**Verification needs:** `make toolbox-yaml test`; live `check_tool_sql.py` (needs application-default credentials).

### REQ-012: Current model is backed up before any training

**Applies when:** Before the first training run of `heat_offset_model_v2` or `surface_heat_model`.

**Obligation:** The current `heat_offset_model` MUST be exported to Cloud Storage and the export path plus the git commit of the template that built it MUST be recorded.

**Acceptance criteria:** `EXPORT MODEL` output exists at a recorded `gs://` path; docs/ARCHITECTURE.md (or the build notes) names that path and commit.

**Verification needs:** Live `gsutil ls` / `gcloud storage ls` of the export path; source inspection of the recorded note.

### REQ-013: The live model cannot be overwritten during development

**Applies when:** Any commit while v2 is under development or before it is promoted.

**Obligation:** No pipeline template other than the existing `sql/04_train_model.sql` MAY create or replace `heat_offset_model`, and that template MUST NOT be changed to train the v2 feature set.

**Acceptance criteria:** An offline test fails if any rendered SQL other than `sql/04_train_model.sql` contains `CREATE OR REPLACE MODEL` targeting `heat_offset_model` (without the `_v2` suffix), or if `sql/04_train_model.sql` references the new v2 feature columns.

**Verification needs:** Offline test over rendered `sql/*.sql` templates.

## Non-goals

- The budget-cycle site selection, costs and displacement analysis, and the decade relief-per-dollar ranking (separate
  follow-on projects consuming these layers).
- Simulating the temperature effect of planting or paving.
- Heat index per cell, air-temperature labels beyond the single Heat Watch afternoon, new GCP projects.
- Redeploying Agent Runtime / Cloud Run is the team's call after the layers pass checks.

## Anti-goals

- Presenting satellite surface temperature as the air temperature people feel.
- Improving r2 while silently shifting priority away from vulnerable residents.
- Overclaiming: the base is one afternoon of air data plus 14 satellite mornings; say so.

## Left to the builder

Exact smoothing window for LST, null-LST fallback, whether old OSM/density/era features stay (decided by held-out r2,
recorded), the reference-station choice for Layer 3, table/column names beyond those named here, and test layout.

## Open questions

None blocking. Proposed defaults needing confirmation at approval: kill margin 0.02 r2 (REQ-003), Layer-2 ship bar 0.05 r2, threshold
95 F (REQ-009), lever labels `pavement` / `canopy` / `none`.
