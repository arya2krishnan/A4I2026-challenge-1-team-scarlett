# Heat Dispatch Console: React build + FastAPI in one container. Build context = a staging dir with the repo layout
# (scripts/deploy_web.sh assembles it): web/frontend, web/backend, agent/heat_dispatch/planner.py.
FROM node:22-slim AS ui
WORKDIR /ui
COPY web/frontend/package.json web/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/frontend/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY web/backend/requirements.txt web/backend/requirements.txt
RUN pip install -r web/backend/requirements.txt
# The planner is shared with the agent and loaded by path (heat_console/planner_loader.py): keep the repo layout.
COPY agent/heat_dispatch/planner.py agent/heat_dispatch/planner.py
COPY web/backend web/backend
COPY --from=ui /ui/dist web/frontend/dist
RUN useradd -m app && chown -R app /app
USER app
WORKDIR /app/web/backend
CMD ["sh", "-c", "exec uvicorn heat_console.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers"]
