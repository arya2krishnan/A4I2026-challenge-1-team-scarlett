# Enrichment implementation status

User authorized priorities 1–6 and commit/push on November 17, 2026.
Dependent BigQuery outputs are built in priority order. Independent acquisition
and reconciliation preparation can run in parallel.

Source baseline: `qwiklabs-gcp-04-3e58e01275b8.a4i_climate_backup_20261117_214035`.
Output dataset: `qwiklabs-gcp-04-3e58e01275b8.a4i_climate_work_v2`.
Original `a4i_climate` tables and models remain available; no consumer switch
has been made. Recovery instructions are in [DATA_RECOVERY.md](DATA_RECOVERY.md).

## Priority 1 — validated in BigQuery

Outputs: `tract_boundaries_2024`, `chicago_boundary_2024`, `cell_tract_map`,
`tract_acs_2024`, `tract_vulnerability_2024`.

- All **5,053 unique cells** retained; every cell has exactly one containing
  Cook County tract.
- **1,305 assignments corrected**, covering **784 distinct mapped tracts**.
- Heat labels, observation counts and spatial hold-out membership unchanged:
  1,649 measured cells, 442 held-out measured cells.
- Three cell centers disagree with the Census city boundary; one requires
  tract `17031820901`, excluded by the primary Chicago-overlap selection.
  It is explicitly retained as an additional boundary tract.
- ACS2024 county source has **1,332 unique tracts**. The working vulnerability
  table has **800**: 799 primary Chicago-intersecting tracts plus that one
  required county-edge tract. Estimates remain whole-tract values.
- Population, 65+, no-vehicle households, poverty counts/universes, social
  indicators, median age and income use the same 2020–2024 estimate period,
  with count/median margins of error and explicit universes retained.
- Three zero-denominator tracts have null rates and no vulnerability rank;
  no median imputation was needed for populated tracts.

Live assertions check key uniqueness, complete cell/ACS coverage, vintage,
universe consistency and unchanged labels/splits. Fourteen focused tests and
the acquisition/runner typechecks passed. Job IDs and aggregate results are
recorded in ignored `data/enrichment/priorities/progress.json`.

## Priorities 2–6

In progress. Facility reconciliation and regional routing acquisition were
prepared independently while priority 1 ran. Event-date validation initially
uses November 17, 2026 unless the team specifies another planning date; this
does not imply a heat event is occurring on that date.

## Reproduce priority 1

```bash
.venv/bin/python scripts/load_chicago_acs_aligned.py
.venv/bin/python scripts/run_data_priorities.py geography
.venv/bin/python scripts/run_data_priorities.py census
```

The runner writes only to a separate working dataset and records completed
jobs. Its SQL guard rejects writes to original or backup namespaces. Local
source caches and recovery archives are excluded from Git.
