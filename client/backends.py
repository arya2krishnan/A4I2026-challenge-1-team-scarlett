"""Two interchangeable backends with the same interface.

LocalBackend  runs the agent IN-PROCESS (ADK Runner + SQLite sessions). Fast edit-run loop: `make run-local`.
              Needs the MCP Toolbox server running (`make toolbox-local`) and your gcloud ADC.
RemoteBackend calls the agent deployed on Agent Runtime. This is what the Cloud Run client uses.
"""
from __future__ import annotations

import asyncio
import os
import queue
import sys
import threading
from pathlib import Path
from typing import Any, Iterator

from blocks import blocks_from_event, messages_from_events

_DONE = object()
APP_NAME = "heat_dispatch"


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    for n in names:
        if isinstance(obj, dict) and n in obj:
            return obj[n]
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


def code_version() -> str:
    """Short git commit of the code this process loaded (plus '+edits' if the working tree differs)."""
    import subprocess
    root = Path(__file__).resolve().parents[1]
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "agent", "client"], cwd=root, capture_output=True, text=True,
                               timeout=5).stdout.strip()
        return (sha or "unknown") + ("+edits" if dirty else "")
    except Exception:
        return "unknown"


def make_backend():
    resource = os.environ.get("AGENT_RESOURCE_NAME", "").strip()
    be = RemoteBackend(resource) if resource else LocalBackend()
    be.code_version = code_version()      # captured when the backend (and, locally, the agent code) was loaded
    return be


class LocalBackend:
    label = "local (in-process agent)"

    def __init__(self) -> None:
        from google.adk.runners import Runner
        from google.adk.sessions import DatabaseSessionService

        agent_dir = Path(os.environ.get("LOCAL_AGENT_DIR") or Path(__file__).resolve().parents[1] / "agent").resolve()
        sys.path.insert(0, str(agent_dir))
        from heat_dispatch.agent import root_agent

        data = Path(__file__).resolve().parents[1] / ".data"
        data.mkdir(exist_ok=True)
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True, name="agent-loop").start()
        self.sessions = DatabaseSessionService(db_url=f"sqlite+aiosqlite:///{data / 'sessions.db'}")
        self.runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=self.sessions)

    def _run(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def create_session(self, user_id: str, title: str) -> str:
        return self._run(self.sessions.create_session(app_name=APP_NAME, user_id=user_id, state={"title": title})).id

    def list_sessions(self, user_id: str, limit: int = 30) -> list[dict]:
        resp = self._run(self.sessions.list_sessions(app_name=APP_NAME, user_id=user_id))
        rows = [{"id": s.id, "title": (s.state or {}).get("title") or "Untitled", "updated": s.last_update_time}
                for s in resp.sessions]
        return sorted(rows, key=lambda r: r["updated"], reverse=True)[:limit]

    def get_messages(self, user_id: str, session_id: str) -> list[dict]:
        s = self._run(self.sessions.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id))
        return [] if s is None else messages_from_events([e.model_dump(mode="json", exclude_none=True) for e in s.events])

    def delete_session(self, user_id: str, session_id: str) -> None:
        self._run(self.sessions.delete_session(app_name=APP_NAME, user_id=user_id, session_id=session_id))

    def stream(self, user_id: str, session_id: str, message: str) -> Iterator[dict]:
        from google.genai import types

        content = types.Content(role="user", parts=[types.Part(text=message)])
        q: queue.Queue = queue.Queue()

        async def pump() -> None:
            try:
                async for ev in self.runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
                    q.put(ev.model_dump(mode="json", exclude_none=True))
            except Exception as exc:
                q.put(exc)
            finally:
                q.put(_DONE)

        asyncio.run_coroutine_threadsafe(pump(), self._loop)
        while (item := q.get()) is not _DONE:
            if isinstance(item, Exception):
                raise item
            yield from blocks_from_event(item)


class RemoteBackend:
    label = "deployed (Agent Runtime)"

    def __init__(self, resource_name: str) -> None:
        from agentplatform import Client

        parts = resource_name.split("/")           # projects/<p>/locations/<l>/reasoningEngines/<id>
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip() or parts[1]
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "").strip() or parts[3]
        self._rt = Client(project=project, location=location).runtimes.get(name=resource_name)

    def create_session(self, user_id: str, title: str) -> str:
        return str(_get(self._rt.create_session(user_id=user_id, state={"title": title}), "id", "session_id"))

    def list_sessions(self, user_id: str, limit: int = 30) -> list[dict]:
        resp = self._rt.list_sessions(user_id=user_id)
        rows = []
        for s in _get(resp, "sessions", default=resp) or []:
            state = _get(s, "state", default={}) or {}
            rows.append({"id": str(_get(s, "id")), "title": state.get("title") or "Untitled",
                         "updated": _get(s, "last_update_time", "lastUpdateTime", default=0) or 0})
        return sorted(rows, key=lambda r: r["updated"], reverse=True)[:limit]

    def get_messages(self, user_id: str, session_id: str) -> list[dict]:
        s = self._rt.get_session(user_id=user_id, session_id=session_id)
        events = _get(s, "events", default=[]) or []
        return messages_from_events([e if isinstance(e, dict) else e.model_dump(mode="json") for e in events])

    def delete_session(self, user_id: str, session_id: str) -> None:
        self._rt.delete_session(user_id=user_id, session_id=session_id)

    def stream(self, user_id: str, session_id: str, message: str) -> Iterator[dict]:
        for event in self._rt.stream_query(user_id=user_id, session_id=session_id, message=message):
            yield from blocks_from_event(event)
