"""Load agent/heat_dispatch/planner.py by PATH, so the backend shares the agent's planner without importing the ADK
agent package (whose __init__ builds the whole agent). The Docker image keeps the repo layout for this reason."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PATH = Path(os.environ.get("PLANNER_PATH") or REPO / "agent" / "heat_dispatch" / "planner.py")


def _load():
    if "heat_planner" in sys.modules:
        return sys.modules["heat_planner"]
    spec = importlib.util.spec_from_file_location("heat_planner", PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["heat_planner"] = mod
    spec.loader.exec_module(mod)
    return mod


planner = _load()
