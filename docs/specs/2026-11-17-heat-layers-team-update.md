# Heat model upgrade: status and proposal (Nov 17)

## TL;DR
- We added two new data layers in BigQuery: pavement and tree canopy for every grid cell, and satellite surface
  temperature from 14 summer days (2019–2025).
- Combined with a location trend, they could roughly **double the heat model's accuracy on held-out blocks**
  (r² 0.26 → ~0.56).
- They also let us explain *why* a block is hot (pavement or lack of trees). That's the basis for the budget-cycle and
  decade questions.
- A design is drafted ([design doc](2026-11-17-heat-layers-design.md)), and **two team decisions** are needed before
  building. The live model is unchanged.

## Why we're doing this
We want the agent to grow from the **Today** question (trucks, wellness checks, library hours) into one planning
assistant that also covers:
- **Budget cycle:** where to put three permanent cooling centers.
- **This decade:** where trees or cool pavement buy the most relief per dollar.

All three need a shared heat base. Today's model can't support the other two:
- It learns from one volunteer-driven afternoon (Heat Watch).
- Its held-out r² is 0.26.
- Its land-cover features explain almost nothing, so it can't say *what to change*.

## What's new in BigQuery (`a4i_climate`)
| Table | What it is | Rows |
|---|---|---:|
| `cell_land_cover` | NLCD 2021 impervious % and tree canopy % for each cell and within 300 m | 5,053 |
| `cell_surface_temp` | Satellite (Landsat) surface heat offset per cell: median of 14 clear summer scenes, 2019–2025, cloud-masked | 5,053 |
| `cell_surface_temp_scenes` | The same data, one row per cell per scene | 70,742 |

- All of it is public domain (USGS/USFS), pulled through Earth Engine inside BigQuery. We enabled the Earth Engine API
  on the lab project for this.
- Scripts and docs: `sql/enrich_*.sql`, `scripts/enrich_*`, `docs/sources/land_cover.md`,
  `docs/sources/surface_temperature.md`.

## What we learned (held-out blocks, 442 cells)
| Model of the Heat Watch air offset | r² |
|---|---:|
| Current model | 0.26 |
| Satellite surface heat alone | 0.17 |
| Location trend alone (lat/lon) | 0.51 |
| **Trend + satellite surface heat** | **0.56** |

- **Satellite heat is a strong "why" signal.** It tracks building cover (r 0.51) and green space (−0.42), and it covers
  every block, not just the volunteers' routes.
  - Hottest areas: West Lawn, Clearing, Archer Heights, Gage Park, Brighton Park.
- **It's a weak stand-in for the air temperature people feel.** Roughly 10°F of surface heat ≈ 2°F of air. We'll never
  present it as air temperature.
- **Pavement and canopy alone barely predict the air readings** (about 2%). Most of the Heat Watch signal is a smooth
  citywide gradient.
- **Honest risk:** part of that gradient may come from the order in which volunteers drove their routes, since the
  readings have no timestamps. The satellite data, measured everywhere at the same moment, also shows the southwest
  running hot. So the gradient is at least partly real.

## Proposed design: three layers
| Layer | Learns from | Serves |
|---|---|---|
| **How hot it feels** (replaces the current model) | Heat Watch air offset explained by location trend + satellite heat + land cover | Today, plus the degrees used for the budget question |
| **Why it's hot** (new model) | Satellite heat explained by changeable features (pavement, canopy, buildings), across every block and 14 days | Decade: each cell gets a lever, `pavement`, `canopy` or `none` |
| **How often** | 7 years of station highs (13 stations) + each cell's offset | Budget: dangerous-heat days (≥95°F) per summer, per cell |

**Decided so far:**
- Keep the location trend in the "how hot" model. It's the biggest accuracy gain. The cost: Today's explanations often
  say "location in the city"; changeable causes come from the "why" layer.
- Build the new model **next to the live one** (`heat_offset_model_v2`) and switch only after checks pass, so the
  deployed agent doesn't change by surprise.
- **Pass/fail bars:**
  - The new model must beat the trend alone by ≥0.02 r², or we fall back to trend + land cover.
  - The "why" layer ships only if changeable features add ≥0.05 r² over location alone.
- **Equity audit before and after** the switch, reported with numbers.
- **We won't claim to simulate fixes.** The data can point to a likely cause, but can't say how much cooler a block
  gets after planting.
- The **budget site picker** and the **decade per-dollar ranking** are follow-on projects built on these layers.

**What changes for Today:** the dispatch list will likely shift toward the southwest interior and away from the
lakefront and Loop. Heat enters the ranking as a percentile, so the change is a re-ordering. We'll compare the old and
new top-20 lists before switching.

## Decisions needed from the team
1. **Should the "why" and "how often" layers reach the agent now, or stay as BigQuery tables for the later tools?**
   Recommendation: tables only for now. It keeps this project focused on upgrading Today and roughly halves the tool,
   prompt and test work.
2. **If the new model moves priority away from the most vulnerable areas, does that block the switch?**
   Recommendation: yes, above a threshold. For example, if the share of top-20 sites in the most vulnerable quarter of
   tracts drops by more than 10 points, the switch waits for team review.
