# Dispatch approval API for Cloud Run (built by `make deploy-api` with gcloud run deploy --source api).
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DISPATCH_STORE=firestore
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY dispatch_api ./dispatch_api
RUN useradd -m app
USER app
CMD ["sh", "-c", "exec uvicorn dispatch_api.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
