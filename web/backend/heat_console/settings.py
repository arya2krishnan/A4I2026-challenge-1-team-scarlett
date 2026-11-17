"""Backend settings from environment variables (.env at the repo root when running locally)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[3]
if (REPO / ".env").is_file():
    load_dotenv(REPO / ".env", override=False)


def _s(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    project: str
    location: str
    dataset: str
    toolbox_url: str
    agent_resource_name: str      # empty = run the agent in-process (local dev)
    store: str                    # "bigquery" or "memory"
    dev_user: str                 # identity when no IAP / ID-token header is present (local only)
    nws_user_agent: str
    static_dir: Path


def get_settings() -> Settings:
    store = _s("WEB_STORE") or ("bigquery" if _s("GOOGLE_CLOUD_PROJECT") and _s("K_SERVICE") else "memory")
    return Settings(
        project=_s("GOOGLE_CLOUD_PROJECT"),
        location=_s("GOOGLE_CLOUD_LOCATION", "us-central1"),
        dataset=_s("BQ_DATASET", "a4i_climate"),
        toolbox_url=_s("TOOLBOX_URL", "http://127.0.0.1:5000").rstrip("/"),
        agent_resource_name=_s("AGENT_RESOURCE_NAME"),
        store=store,
        dev_user=_s("WEB_DEV_USER", "local-operator"),
        nws_user_agent=_s("NWS_USER_AGENT", "heat-dispatch-console (hackathon prototype)"),
        static_dir=Path(_s("WEB_STATIC_DIR") or REPO / "web" / "frontend" / "dist"),
    )
