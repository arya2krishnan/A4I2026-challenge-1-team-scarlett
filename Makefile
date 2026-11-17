# Heat Dispatch Assistant (Chicago, Today track). `make help` lists targets.
VENV ?= .venv
PY   := $(VENV)/bin/python
CITY ?= chicago

.PHONY: help setup test data osm model validate-model toolbox-yaml toolbox-local smoke adk-web run-local check-models gcp-setup deploy-toolbox deploy-agent deploy-client enrich-data enrich-weather enrich-vulnerability enrich-geography enrich-environment enrich-transit enrich-cooling enrich-walkability enrich-load typecheck

help:  ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | column -t -s "$$(printf '\t')"

setup:  ## venv (Python 3.11) with everything
	python3.11 -m venv $(VENV)
	$(VENV)/bin/pip install -q --upgrade pip
	$(VENV)/bin/pip install -q -r requirements-dev.txt
	@test -f .env || (cp .env.example .env && echo "Created .env: set GOOGLE_CLOUD_PROJECT")

test:  ## offline tests (no GCP needed)
	$(PY) -m pytest tests -q

data:  ## 1) load the three source tables for Chicago, 2) City of Chicago facilities + neighbourhood boundaries
	bash scripts/load.sh $(CITY)
	$(PY) scripts/load_chicago_facilities.py
	$(PY) scripts/load_chicago_boundaries.py

enrich-data: enrich-weather enrich-environment enrich-transit enrich-walkability  ## fetch public enrichment snapshots locally; see docs/DATA_ENRICHMENT.md

enrich-weather:  ## current hourly NWS forecasts + overnight summaries for six Chicago points
	$(PY) scripts/load_chicago_weather.py

enrich-vulnerability:  ## ACS older adults living alone, disability and children under five (Cook County)
	$(PY) scripts/load_chicago_vulnerability.py --year 2024

enrich-geography: enrich-vulnerability  ## filter the acquired ACS tracts to Chicago using matching-vintage boundaries
	$(PY) scripts/clip_chicago_vulnerability.py

enrich-environment: enrich-geography  ## tract tree canopy and Census rent burden; canopy redistribution terms need confirmation
	$(PY) scripts/load_chicago_environment.py

enrich-transit:  ## CTA stops, routes, calendars and scheduled departures; optional SERVICE_DATE=YYYY-MM-DD
	$(PY) scripts/load_chicago_transit.py $(if $(SERVICE_DATE),--service-date $(SERVICE_DATE))

enrich-cooling:  ## currently published city cooling inventory, preserving unknown operational readiness
	$(PY) scripts/load_chicago_cooling_inventory.py

enrich-walkability: enrich-cooling  ## bounded Loop walking-network pilot (not citywide routing)
	$(PY) scripts/load_chicago_walkability.py

enrich-load:  ## upload acquired snapshots; requires PROJECT=... and optional DATASET=...
	$(PY) scripts/load_enrichment_snapshots.py --project $(PROJECT) --dataset $(or $(DATASET),a4i_climate)

typecheck:  ## typecheck the enrichment acquisition, geography and upload scripts
	$(PY) -m mypy --follow-imports=silent --ignore-missing-imports scripts/load_chicago_vulnerability.py scripts/clip_chicago_vulnerability.py scripts/load_chicago_environment.py scripts/load_chicago_weather.py scripts/load_chicago_transit.py scripts/load_chicago_cooling_inventory.py scripts/load_chicago_walkability.py scripts/load_enrichment_snapshots.py

osm:  ## one-off: pull the Chicago slice of OpenStreetMap land cover (buildings, green, paved, roads) into BigQuery
	$(PY) scripts/run_sql.py 00

model:  ## build grid cells, vulnerability, site context, TRAIN the BQML model, evaluate, validate (steps 01-06; needs `make osm` once first)
	$(PY) scripts/run_sql.py 01 02 03 04 05 06

validate-model:  ## dry-run every SQL step against BigQuery (no cost, no writes)
	$(PY) scripts/run_sql.py --dry-run 01 02

toolbox-yaml:  ## regenerate toolbox/tools.yaml from toolbox/build_tools_yaml.py
	$(PY) toolbox/build_tools_yaml.py

toolbox-local:  ## serve MCP Toolbox on 127.0.0.1:5000 against your BigQuery (leave running)
	bash scripts/toolbox_local.sh

smoke:  ## call every Toolbox tool once (needs toolbox-local running); run this before trusting the agent
	$(PY) scripts/smoke_toolbox.py

adk-web:  ## ADK dev UI (debug tool calls, events, state); needs toolbox-local running
	cd agent && ../$(VENV)/bin/adk web --port 8000 .

run-local:  ## Streamlit client with the agent in-process; needs toolbox-local running
	$(VENV)/bin/streamlit run client/app.py

check-models:  ## does MODEL answer for this project?
	$(PY) scripts/check_models.py

gcp-setup:  ## one-time: enable APIs, service accounts, roles (needs project admin)
	bash scripts/setup_gcp.sh

deploy-toolbox:  ## MCP Toolbox -> Cloud Run (private, min-instances=1)
	bash scripts/deploy_toolbox.sh

deploy-agent:  ## agent -> Agent Runtime (NEW=1 for a fresh instance)
	bash scripts/deploy_agent.sh

deploy-client:  ## Streamlit client -> Cloud Run
	bash scripts/deploy_client.sh
