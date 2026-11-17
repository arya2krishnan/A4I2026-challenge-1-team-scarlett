# Runbook: from empty project to deployed agent

Order matters. Each step says what proves it worked. Steps 1-5 have been run end to end on project
`qwiklabs-gcp-04-3e58e01275b8` (see the status table in ARCHITECTURE.md).

## 0. Once
```bash
make setup                                   # .venv with everything pinned
# edit .env: GOOGLE_CLOUD_PROJECT=<your project>
gcloud auth login && gcloud auth application-default login
gcloud auth application-default set-quota-project <your project>
gcloud config set project <your project>
make test                                    # 56 offline tests; no GCP needed
make check-models                            # proves MODEL answers for this project; else change MODEL in .env
```

## 1. Data (data lane)
```bash
make data          # 3 source tables (load.sh chicago) + City of Chicago facilities + neighbourhood boundaries
make osm           # one-off, ~3 GB scanned: OpenStreetMap buildings/green/paved/roads for Chicago -> osm_chicago
```
Proof: `load.sh` prints row counts and the intra-city spread (expect ~49k street readings; spread > 10°F).

## 2. Model (data lane)
```bash
make validate-model   # BigQuery dry-run of steps 01-02: catches a wrong column name before any cost
make model            # 01 grid (clipped to the city), 02 vulnerability, 03 site context, 04 TRAIN, 05 EVALUATE, 06 validate
```
Proof: step 06 prints PASS for every check; step 05 prints held-out MAE/RMSE/r2 next to a "predict zero" baseline.
**Read step 05 before going on.** r2 > 0.9 means leakage; r2 near 0 means the features do not explain heat and the
pitch must say so. Either way those numbers go in the deck (the agent quotes them through `model_card`).

## 3. Tools through MCP (agent lane)
```bash
python scripts/check_tool_sql.py   # runs every tool's exact SQL against BigQuery (no Toolbox needed)
make toolbox-local    # or: python scripts/toolbox_proxy.py (local port 5000 -> the deployed private Toolbox)
make smoke            # calls all 9 tools once through MCP
```
Proof: `ALL OK`. A FAIL names the tool and the BigQuery error: fix `toolbox/build_tools_yaml.py`, then `make toolbox-yaml`.

## 4. Agent, locally
```bash
make run-local        # Streamlit, agent in-process (fast loop)       http://localhost:8501
make adk-web          # ADK dev UI: inspect every tool call, event and state key
```
Ask the three example questions in the UI. Check the "tool calls" expander: `rank_priority_sites` must appear, and
the dispatch sheet's coordinates must match its rows.

## 5. Deploy
```bash
make gcp-setup        # once, needs project admin: APIs + toolbox/agent service accounts + roles
make deploy-toolbox   # Cloud Run, private, min-instances=1; writes TOOLBOX_URL to .env; grants run.invoker to the agent SA
make deploy-agent     # Agent Runtime; writes AGENT_RESOURCE_NAME to .env
make deploy-client    # Streamlit on Cloud Run (IAM-protected; use `gcloud run services proxy` to view it)
```
Proof: with `AGENT_RESOURCE_NAME` set, `make run-local` talks to the deployed agent (the sidebar says "deployed").

## When something breaks
| Symptom | Likely cause |
|---|---|
| `make model` fails at 01 with "Not found: community_areas" | run `make data` (it loads the neighbourhood boundaries) |
| `make model` fails at 01 with "osm_chicago" not found | run `make osm` once |
| `make model` fails at 01 with "Unrecognized name" | `load.sh chicago` not run, or table columns differ: compare with the notebook |
| step 03 fails: `cooling_facilities` not found | run `python scripts/load_chicago_facilities.py` |
| step 06 FAIL "unmeasured cells exist" | `CAND_RADIUS_CELLS` in `sql/chicago.json` too small |
| `smoke` fails with `Not found: Model` | step 04 did not finish; rerun `python scripts/run_sql.py 04` |
| Agent says it "cannot reach the toolbox" when deployed | agent identity lacks `run.invoker` on the Toolbox service |
| Deploy rejects the env file | an env value is empty: the script drops empty values, check `.env` for stray lines |
