# Architecture and decisions

**Track:** Today. **City:** Chicago. **User:** an emergency-management duty officer who must decide, by tomorrow's
heat, where hydration trucks go, who gets wellness checks, and which libraries stay open longer.

```mermaid
flowchart LR
  U[Duty officer] -- IAP --> W
  subgraph CR[Cloud Run: heat-dispatch-web]
    W[React console\nmap lenses, cards, chat] --> B[FastAPI backend\nboard + planner]
  end
  B -- "MCP, ID token\n(data + recommendations)" --> T
  B -- "chat: stream_query +\nsession state (console_context / console_plan)" --> A
  B -- "approvals + plan versions" --> AP[(BigQuery\ndispatch_approvals,\ndispatch_plan_versions)]
  C[Streamlit client\nlegacy, until parity] -- "stream_query (ADC)" --> A
  subgraph AR[Agent Runtime]
    A[heat_dispatch_agent\nADK + Gemini]
    A --- P[Python tools:\nlocate_place, get_forecast_high,\nheat_risk_for_forecast, build_dispatch_plan,\nset_operator_constraints, replan_dispatch]
  end
  A -- "MCP, ID token" --> T[MCP Toolbox\nCloud Run, min-instances=1]
  T -- "parameterized SQL, read-only SA" --> BQ[(BigQuery)]
  BQ --- M{{BQML heat_offset_model\nML.EXPLAIN_PREDICT}}
  BQ --- D[(Heat Watch, GHCN, ACS,\nChicago facilities)]
  A -. "forecast" .-> NWS[api.weather.gov]
```

## Why each piece exists
| Piece | Job | Why this and not something simpler |
|---|---|---|
| **BQML `LINEAR_REG`** on grid cells | Predict the *offset* (°F hotter than the Chicago average) for every ~330 m cell, driven or not | The README's requirement; free-tier; supports `ML.EXPLAIN_PREDICT`; attributions are speakable |
| **MCP Toolbox** (11 SQL tools) | The agent's only path to BigQuery | We *consume* an MCP server (required) *and* define our own tools (required). Ranking, explanation, audit are parameterized SQL, so the LLM never writes SQL |
| **Python tools** | Things that are not one query: forecast + offset arithmetic, place lookup, assembling the dispatch sheet | The README: "the work that isn't a single query" |
| **Stash callback + `build_dispatch_plan`** | The sheet is built from stored tool output | The language model cannot alter a coordinate or a count; it only writes prose around them |
| **Heat Dispatch Console** (`web/`) | The duty desk's screen: 6 map lenses, City sites, recommendation cards with Approve / Skip, operator chat | Concept D (`docs/mockups/concept-d`). React for a stateful board; FastAPI so the browser never touches BigQuery or Toolbox |
| **Shared planner** (`agent/heat_dispatch/planner.py`) | Turns Toolbox rows + constraints + approvals into plan items, a diff, and capacity un-approvals | One deterministic implementation for slider re-plans (backend) and chat re-plans (agent). Stdlib only, so the backend loads it by path without the ADK agent |
| **Console tools** (`console.py`) | `set_operator_constraints` + `replan_dispatch`: the agent changes constraints, re-plans from fresh Toolbox rows, writes `console_plan` to session state | The backend reads the plan from session state after the turn, so a number never passes through model text |
| **Approvals in BigQuery** | Every approve / un-approve / skip / capacity un-approval: who, when, item, plan version; every plan version's full payload | An audit trail the desk can query; the web identity may write only these two tables |
| **Guard callback** | Refuses points outside Chicago without calling a tool | A deterministic failure path, not a prompt hope |
| **Facilities (City of Chicago)** | 79 libraries, senior centers, colleges... with hours | Bring-your-own-data; turns "hot" into "hot and far from anywhere cool" |
| **Community areas (City of Chicago)** | 77 neighbourhood polygons | Clips the grid to the city and names every stop |
| **OpenStreetMap (ODbL)** | buildings, green, paved-use land, roads within 300 m | Built-environment features; attribute (c) OpenStreetMap contributors |

## Decisions we can defend
1. **Predict the offset, not the temperature.** Single afternoon, one-hour window: differences are purely spatial.
   Expected air temp at a site = forecast + offset, computed by `heat_risk_for_forecast`.
2. **Physical features only in the model** (distance to lake, to the Loop, density, housing age). Demographics are
   added *after* (vulnerability index) and then *audited*, so the audit is not circular. Race is not loaded or used.
3. **Spatial hold-out.** ~20% of 2.7 km superblocks are held out whole; a random row split would leak because
   neighbouring cells share a temperature. `05_evaluate.sql` compares against "always predict zero".
4. **Vulnerability = 65+, no car, poverty**, equal-weight percentile ranks, missing → city median. No outcome tuning.
5. **Priority = (heat_weight·heat + (1-heat_weight)·vulnerability) × (0.6..1.0 by distance from indoor cooling).**
   `heat_weight` is a tool parameter: the officer can move it and the equity audit shows the consequence.
6. **Spacing:** best cell per ~1.7 km block, so five trucks are not parked on one hot corner.
7. **Interface: the Heat Dispatch Console** (`web/`, React + FastAPI on Cloud Run, behind IAP). It replaced Streamlit
   (`client/` is kept until parity). The browser talks only to the backend; data and recommendations come from Toolbox
   tools (`tract_map_layer`, `list_sites`, the ranking tools), chat goes to the agent. Scoring still runs
   `ML.EXPLAIN_PREDICT` in BigQuery. `adk web` is kept for debugging.
8. **Toolbox on Cloud Run with min-instances=1, private.** No cold start on the first (demo) request; only the agent's
   identity can invoke it; the Toolbox SA is read-only on the dataset (IAM, not prompt, enforces read-only).
9. **Chat re-plans through session state, not text.** Before each turn the backend writes `console_context` (plan
   version, day, constraints, approvals, skips, item keys) into the session with ADK's session service (Vertex AI
   Sessions when deployed: the store Agent Runtime uses). The agent's `replan_dispatch` writes `console_plan` (with the
   turn id); the backend adopts it only if the turn id matches, and re-runs the planner if the board moved meanwhile.
10. **Approvals stay pinned across re-plans.** When capacity drops below what is approved, the lowest-priority
    approvals are un-approved and the operator is told which (logged as `auto_unapprove` by `system`).
11. **Console mapping of the mockup's controls.** Rank-by presets set `heat_weight` (balanced 0.5, vulnerable-first 0.2,
    heat-only 1.0). The hot cutoff is a minimum modelled offset (`min_offset`). Wellness = top tracts from
    `rank_wellness_check_tracts`; libraries = open-that-weekday branches scored by ranked tracts within 1.2 km not
    already given a team; trucks = `rank_priority_sites` cells outside wellness tracts. The mockup's 65+-share and
    walking-radius sliders had no backing in our data and were dropped.

## Honest limits (say these in the pitch)
- Heat Watch is **one afternoon driven by volunteers**; the model has seen one weather pattern and fixed routes.
- **Weak model, stated plainly.** On spatially held-out blocks the physical-feature model gets r2 ~0.26 (RMSE 2.06F vs 2.41F
  for "always predict the average"). Its offsets are small (top sites about +1.4F) next to the 20F spread of raw readings.
  Diagnostics (linear models, same held-out blocks): land cover alone r2 0.01; a plain lat/lon quadratic trend 0.50;
  physical + trend 0.51. So most of the signal in this campaign is a smooth geographic gradient (lake effect, but possibly
  also the order in which volunteers drove their routes), and local land cover barely adds to it. Nothing was tuned on the
  held-out blocks. Ranking is therefore "relatively hotter and more vulnerable", not a measured temperature.
- Lakefront geometry is hand-traced (~300 m); the Loop is a point. Both are proxies.
- Density is estimated from tract centroids, so it is coarse at tract borders.
- ACS demographics are tract-level 5-year estimates; a tract is counted whole in `who_lives_near`.
- The offset says *where relatively hotter*, not *what it feels like*: heat index needs humidity, passed separately.
- Facility hours are a snapshot; holiday closures are free text. The agent says "confirm".
- We cannot simulate an intervention's effect (no data), and we do not claim to.
- The console keeps the live board in memory (Cloud Run `max-instances=1`); BigQuery holds every version and is
  reloaded on start. Two operators see one shared board; there is no per-operator draft.
- Tract outlines come from `bigquery-public-data.geo_census_tracts.census_tracts_illinois`; a tract whose geometry
  does not join (vintage mismatch with ACS 2022) is simply not drawn.

## Verified live (project qwiklabs-gcp-04-3e58e01275b8)
| Step | Result |
|---|---|
| Data load | Chicago: 48,855 readings (22F spread, no timestamps as expected), 1,627 tracts, 13 stations from 2019 |
| Model pipeline 01-06 | all checks PASS; 5,053 city cells (1,649 measured, 3,313 never driven) |
| 9 Toolbox tools | run live, including ML.EXPLAIN_PREDICT; deployed Toolbox (Cloud Run, private) answers over MCP |
| Agent on Agent Runtime | calls Toolbox with its own ID token; answers with neighbourhood, reasons and equity audit |
| Client on Cloud Run | 200 with identity token, 403 without |
| Console (`web/`) | offline only so far: `make test` (planner, console tools, backend with fake Toolbox/agent, React flows); not yet deployed |

Reliability on the deployed agent (canned "plan tomorrow" prompt): 1/3 and 1/6 before fixes, 12/12 after (event-loop, same-step race, transfer ping-pong; see CLAUDE.md gotchas).

Bugs the live run caught: MCP returns BigQuery structs as `[name, value]` pairs not objects; the Heat Watch footprint
includes suburbs (Berwyn), so cells are clipped to the 77 community areas; O'Hare ranked first until the default density
floor was raised to 3,000 people/km2.

## Judging map
| Dimension | Where to look |
|---|---|
| Impact & insight | dispatch sheet (stand-on coordinates, who is nearby, nearest cooling, library hours) |
| Technical execution | `toolbox/tools.yaml` (MCP), `sql/04_train_model.sql` (BQML), `agent/heat_dispatch/` (ADK), `scripts/deploy_*.sh` (Agent Runtime) |
| Rigor & judgment | `sql/05_evaluate.sql`, `sql/06_validate.sql`, `equity_audit` tool, this file's limits |
| Craft | `web/` (console), `docs/mockups/concept-d` (the design it implements), `docs/` |

## Model v2 candidate: `heat_offset_lst` (validated, NOT promoted)
Design: [docs/specs/2026-11-17-heat-layers-design.md](specs/2026-11-17-heat-layers-design.md), Layer 1 ("how hot it feels").
Built beside the live model by `bash scripts/run_v2.sh build` (`sql/v2/`): view `site_context_lst` (live `site_context`
+ location trend, Landsat surface heat averaged over the 3x3 neighbourhood, NLCD imperviousness and canopy within 300 m)
and models `heat_offset_trend_only`, `heat_offset_lst`. Same label, training rows (1,207) and options as `sql/04`.
The live `heat_offset_model`, `site_context` and `toolbox/tools.yaml` are untouched; `tests/test_model_v2_sql.py`
fails if any template other than `sql/04` would recreate the live model.

**Held-out superblocks (442 cells, never seen in training), 2026-11-17:**

| Model | r2 | RMSE (F) | MAE (F) |
|---|---:|---:|---:|
| Always predict the city average | 0.00 | 2.41 | 1.44 |
| Live model (physical features) | 0.26 | 2.06 | 1.44 |
| Location trend only | 0.50 | 1.68 | 1.24 |
| **v2: trend + surface heat + land cover** | **0.59** | **1.54** | **1.22** |

- Kill criterion (REQ-003, v2 must beat trend-only by >= 0.02 r2): **PASS**, margin +0.084.
- Edge check: 0 unmeasured cells predict outside the measured range (-13.9..+6.7 F); v2 predictions span -8.1..+3.5 F
  (coolest: lakefront Rogers Park).
- Equity audit, top 20 truck sites, heat_weight 0.5 (`scripts/compare_v2.py`): share of sites in the top vulnerability
  quartile 76.5% -> 76.5% (unchanged); mean vulnerability 0.799 -> 0.815; share 65+ 17.9% -> 19.8%; poverty
  30.4% -> 25.9%; households without a car 31.9% -> 29.7%. Citywide: 18.7% / 0.575 / 12.8% / 17.3% / 23.6%.
- Ranking shift: 2 of 20 exact cells unchanged; sites move toward the South Side (Calumet Heights, Greater Grand
  Crossing, South Shore, Auburn Gresham, South Deering) and away from the West Side (East/West Garfield Park,
  Humboldt Park); Chatham, Chicago Lawn, Austin and North Lawndale stay in the top 10.
- Caveats: surface heat is satellite SURFACE temperature at ~10:30, used as an input, never shown as air temperature;
  the location trend may partly reflect the order volunteers drove (Heat Watch has no timestamps), though Landsat,
  measured everywhere at once, also shows the southwest/south running hot.
- Rollback / backup: nothing to roll back while unpromoted. Full snapshot of tables and all models:
  `a4i_climate_backup_20261117_214035` (docs/DATA_RECOVERY.md). The live model can also be rebuilt from `sql/04`.
- **Promoted 2026-11-17 ~22:10 UTC.** `toolbox/build_tools_yaml.py` now uses `MODEL = heat_offset_lst` and
  `CONTEXT = site_context_lst`; tools request all attributions and sum the five `trend_*` terms into one
  `location_trend` reason before keeping the top 3/4. All 11 tools ran live against BigQuery before deploy. Deployed:
  secret `heat-toolbox-tools` version 7, Cloud Run `heat-toolbox` (us-central1) revision `heat-toolbox-00006-28b`
  (previous: `heat-toolbox-00005-jrd`, secret version 6). The us-west2 `heat-toolbox` also mounts `:latest` and picks
  up v2 on its next instance start. Live global importance: location 1.69 F, lake band 1.45, surface heat 0.31,
  canopy 0.03, pavement 0.01 (land cover adds little to the AIR model; it matters for the planned "why" layer).
- **Rollback** (both services read the secret's `:latest`, so routing traffic to the old revision alone is NOT enough):
  `gcloud secrets versions access 6 --secret heat-toolbox-tools > /tmp/v6.yaml && gcloud secrets versions add
  heat-toolbox-tools --data-file=/tmp/v6.yaml`, then `bash scripts/deploy_toolbox.sh` from `main` (or
  `gcloud run services update heat-toolbox --region us-central1 --update-labels rollback=1` to force a new revision).
- **Not yet redeployed:** the agent (Agent Runtime) and web console still carry their old label maps, so the new
  feature names (`location_trend`, `surface_heat_f`, ...) render as plain words until they are redeployed from this branch.

## Enriched toolset on the v2 model (DEPLOYED 2026-11-17 22:45 UTC)
`toolbox/tools.enriched.yaml` (toolset `heat_dispatch_enriched`) now scores the corrected context with the live v2
model: view `a4i_climate_work_v2.site_context_enriched_lst` (`sql/v2/20_site_context_enriched_lst.sql`) adds the
v2-derived inputs (trend, 3x3 surface heat) to `site_context_enriched`. The model's inputs and label are identical
there (held-out r2 0.588, RMSE 1.535 F, same 442 cells); the enrichment corrects the ranking inputs (ACS 2024,
Chicago-only tracts, facility readiness). All 11 enriched tools ran live on 2026-11-17.

Top 20 truck sites (heat_weight 0.5), live vs enriched: share in the top vulnerability quartile 76.5% (city 18.7%,
4.1x) vs 50.0% (city 11.7%, 4.3x); mean vulnerability +0.24 vs +0.23 over city; share 65+ 20.6% vs 23.1%. The
vulnerability index itself was rebuilt, so compare lift over city, not raw shares. Every nearest cooling site is
`nearest_cooling_event_verified = false` (listed, not confirmed open/AC for the event).
**Deployed:** the enriched file keeps the toolset name `heat_dispatch` (what the agent and console load) and is
deployed with `TOOLS_SRC=toolbox/tools.enriched.yaml bash scripts/deploy_toolbox.sh` -> secret `heat-toolbox-tools`
v8, Cloud Run `heat-toolbox` (us-central1) revision `heat-toolbox-00007-79n`. Verified over MCP: 11 tools in
`heat_dispatch`; `rank_priority_sites` returns ACS 2024 rows with `nearest_cooling_event_verified`; run.invoker still
granted to heat-agent and heat-web.

| Secret version | Model | Context | Live |
|---|---|---|---|
| v6 | heat_offset_model (original) | site_context | until 21:59 UTC |
| v7 | heat_offset_lst (v2) | site_context_lst | 21:59-22:45 UTC |
| v8 | heat_offset_lst (v2) | site_context_enriched_lst | from 22:45 UTC |

**Rollback:** `bash scripts/rollback_toolbox.sh 7` (v2, original data) or `... 6` (original model). Plain
`bash scripts/deploy_toolbox.sh` (no TOOLS_SRC) also returns to v2 on original data, so anyone deploying from defaults
reverts the enrichment: always pass `TOOLS_SRC=toolbox/tools.enriched.yaml` while v8 is the intended live state.
