# Heat Dispatch Assistant (Chicago, Today track). `make help` lists targets.
VENV ?= .venv
PY   := $(VENV)/bin/python
CITY ?= chicago

.PHONY: help setup test data osm model validate-model toolbox-yaml toolbox-local smoke adk-web run-local check-models gcp-setup deploy-toolbox deploy-agent deploy-client load-sites web-build run-web web-dev test-web deploy-web

help:  ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | column -t -s "$$(printf '\t')"

setup:  ## venv (Python 3.11) with everything
	python3.11 -m venv $(VENV)
	$(VENV)/bin/pip install -q --upgrade pip
	$(VENV)/bin/pip install -q -r requirements-dev.txt
	@test -f .env || (cp .env.example .env && echo "Created .env: set GOOGLE_CLOUD_PROJECT")

test:  ## offline tests (no GCP needed): Python, plus the web frontend when its node_modules are installed
	$(PY) -m pytest tests -q
	@if [ -d web/frontend/node_modules ]; then $(MAKE) --no-print-directory test-web; else echo "(skipping web frontend tests: run 'cd web/frontend && npm ci')"; fi

test-web:  ## web console frontend tests (Vitest + Testing Library) and typecheck
	cd web/frontend && npx tsc -b && npx vitest run

load-sites:  ## City of Chicago heat-relief sites (data/chicago/sites) -> BigQuery chi_site_* tables (the console needs them)
	bash tools/load_chicago_sites_bq.sh

data:  ## 1) load the three source tables for Chicago, 2) City of Chicago facilities + neighbourhood boundaries
	bash scripts/load.sh $(CITY)
	$(PY) scripts/load_chicago_facilities.py
	$(PY) scripts/load_chicago_boundaries.py

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

web-build:  ## build the console frontend into web/frontend/dist
	cd web/frontend && npm ci --no-audit --no-fund && npm run build

run-web: web-build  ## console (FastAPI + built React) on :8080; agent in-process unless AGENT_RESOURCE_NAME is set; needs toolbox-local
	cd web/backend && ../../$(VENV)/bin/uvicorn heat_console.main:app --port 8080 --reload --reload-dir . --reload-dir ../../agent

web-dev:  ## frontend hot reload on :5173 (proxies /api to :8080; run `make run-web` in another terminal)
	cd web/frontend && npm run dev

deploy-web:  ## console -> Cloud Run (own service account, IAP; WEB_USERS=user:a@x.org,... to grant access)
	bash scripts/deploy_web.sh
