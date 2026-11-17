# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Team Scarlett's solution for **Agents for Impact 2026, Challenge 1 (Urban Heat)**. Decisions already made (do not re-litigate):
**track = Today** (emergency management: hydration trucks, wellness checks, extended library hours), **city = Chicago**,
**MCP server = MCP Toolbox on Cloud Run** (min-instances=1), **agent deployed to Agent Runtime**, **UI = Streamlit** (runs
locally in-process or on Cloud Run). `README.md` is the organizers' challenge brief (grep it; judging criteria are at the end).
`/Users/sanjay2/google-events/agent4impact-2026/ai4impact/` holds the sample multi-agent apps this design borrows from
(its `CLAUDE.md` lists ADK/Agent Runtime gotchas). That sample uses ADK's native BigQueryToolset; this repo uses MCP Toolbox instead.

## Commands (`make help`; Python 3.11 venv in `.venv`, config in `.env`)

```bash
make test                      # 55 offline tests (no GCP); single: .venv/bin/python -m pytest tests/test_python_tools.py::test_plan_uses_stored_rows_verbatim -q
make data | model              # load tables + facilities, then run sql/01..06 (builds grid, trains BQML, evaluates)
make toolbox-yaml              # regenerate toolbox/tools.yaml after editing toolbox/build_tools_yaml.py (a test fails if stale)
make toolbox-local | smoke     # serve MCP Toolbox on :5000 / call every tool once against live BigQuery
make run-local | adk-web       # Streamlit with in-process agent / ADK dev UI (both need toolbox-local)
make gcp-setup deploy-toolbox deploy-agent deploy-client   # deploy order; docs/RUNBOOK.md has the proofs per step
```
Do not run `scripts/publish` notebooks (maintainers only). Invoke shell scripts with `bash`.

## Architecture (read docs/ARCHITECTURE.md for the why)

- `sql/NN_*.sql` are templates (`{{PROJECT}}`, `{{DATASET}}`, constants in `sql/chicago.json`) rendered and run by `scripts/run_sql.py`.
  Pipeline: 01 grid cells (~330 m; label = measured offset; features physical only) → 02 tract vulnerability → 03 site_context
  (+ nearest indoor cooling/library) → 04 `CREATE MODEL` (BQML LINEAR_REG, TRANSFORM) → 05 evaluate on spatially held-out blocks → 06 checks.
- `toolbox/build_tools_yaml.py` GENERATES `toolbox/tools.yaml` (9 `bigquery-sql` tools). Four tools share one scoring CTE that
  runs `ML.EXPLAIN_PREDICT` live. `${VAR}` placeholders are resolved by `scripts/render_toolbox.py` at deploy.
- `agent/heat_dispatch/` is the ADK agent: Toolbox toolset + Python tools. `agent.stash_tool_results` (after-tool callback) saves
  ranked rows to session state; `dispatch.build_dispatch_plan` renders the sheet from that state so the LLM cannot alter numbers.
  `agent.guard_point_tools` refuses out-of-Chicago coordinates. Prompt rules live in `prompts.py` (a test checks tool names match tools.yaml).
- Model predicts an OFFSET (°F hotter than the Chicago average), never a temperature. Race is not used anywhere; the equity audit reports outcomes.

## Status / caveats

Deployed and verified on project `qwiklabs-gcp-04-3e58e01275b8` (ids/URLs are in the git-ignored `.env`): Toolbox on Cloud Run
(private), agent on Agent Runtime, Streamlit client on Cloud Run. `make test` = 56 offline tests. Model is weak by design of the
data (held-out r2 ~0.26; a lat/lon trend alone gets 0.50: see docs/ARCHITECTURE.md). Open decision: whether to add a coarse
location-trend term to the model. `scripts/check_tool_sql.py` runs every tool's SQL directly; `scripts/ask.py` queries the agent
(needs `python scripts/toolbox_proxy.py` for a local run against the private Toolbox). macOS bash 3.2 cannot run `scripts/load.sh`
(`${var^^}`): run its three `bq load --replace` commands instead.

## Conventions

`.env`, `.venv`, `.bin`, `toolbox/tools.rendered.yaml` and this file are git-ignored. No commits unless asked.
