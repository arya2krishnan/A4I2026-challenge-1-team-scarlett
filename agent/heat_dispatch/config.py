"""One Settings object driven by environment variables (.env locally, baked env vars when deployed)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).resolve().parent
# Nearest .env wins: the agent folder (written by the deploy script), then the repo root.
for _env in (_HERE / ".env", *(p / ".env" for p in _HERE.parents[:3])):
    if _env.is_file():
        load_dotenv(_env, override=False)

# Gemini through Vertex AI + Application Default Credentials, never an API key.
os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "1")


def _s(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    project: str
    location: str              # region of Agent Runtime / Cloud Run (NOT the model endpoint)
    model: str
    model_location: str
    toolbox_url: str           # MCP Toolbox server: http://127.0.0.1:5000 locally, the Cloud Run URL when deployed
    toolbox_toolset: str
    maps_api_key: str          # optional: reverse-geocodes stops into street addresses
    contact_agent: str         # User-Agent for api.weather.gov (it asks for an identifying string)


def get_settings() -> Settings:
    return Settings(
        project=_s("GOOGLE_CLOUD_PROJECT"),
        location=_s("GOOGLE_CLOUD_LOCATION", "us-central1"),
        model=_s("MODEL", "gemini-3.6-flash"),
        model_location=_s("MODEL_LOCATION", "global"),
        toolbox_url=_s("TOOLBOX_URL", "http://127.0.0.1:5000").rstrip("/"),
        toolbox_toolset=_s("TOOLBOX_TOOLSET", "heat_dispatch"),
        maps_api_key=_s("MAPS_API_KEY"),
        contact_agent=_s("NWS_USER_AGENT", "heat-dispatch-agent (hackathon prototype)"),
    )
