"""Talk to the ADK agent: in-process for local dev, or the deployed Agent Runtime instance.

Per chat turn the backend (1) writes `console_context` into the session state, (2) streams the agent's reply,
(3) reads `console_plan` back from the session state. Step 1 and 3 go through ADK's session service, which for a
deployed agent is Vertex AI Sessions: the same store Agent Runtime reads and writes.
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Protocol

APP_NAME = "heat_dispatch"


class AgentGateway(Protocol):
    async def create_session(self, user_id: str, state: dict) -> str: ...
    async def push_state(self, user_id: str, session_id: str, delta: dict) -> None: ...
    def stream(self, user_id: str, session_id: str, message: str) -> AsyncIterator[dict]: ...
    async def get_state(self, user_id: str, session_id: str) -> dict: ...


def blocks_from_event(event: dict):
    """One ADK event dict -> UI blocks: text | tool_call | tool_result (thoughts dropped)."""
    author = event.get("author")
    for part in (event.get("content") or {}).get("parts") or []:
        if part.get("thought"):
            continue
        call = part.get("function_call") or part.get("functionCall")
        resp = part.get("function_response") or part.get("functionResponse")
        if call:
            yield {"kind": "tool_call", "author": author, "name": call.get("name")}
        elif resp:
            yield {"kind": "tool_result", "author": author, "name": resp.get("name")}
        elif part.get("text"):
            yield {"kind": "text", "author": author, "text": part["text"]}


async def _append_state(svc: Any, app_name: str, user_id: str, session_id: str, delta: dict) -> None:
    from google.adk.events import Event, EventActions

    session = await svc.get_session(app_name=app_name, user_id=user_id, session_id=session_id)
    if session is None:
        raise KeyError(session_id)
    await svc.append_event(session, Event(author="console", invocation_id=f"console-{uuid.uuid4().hex[:12]}",
                                          actions=EventActions(state_delta=delta), timestamp=time.time()))


class LocalAgent:
    """ADK Runner in this process (needs `make toolbox-local` and gcloud ADC for Gemini)."""

    def __init__(self) -> None:
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService

        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "agent"))
        from heat_dispatch.agent import root_agent

        self.sessions = InMemorySessionService()
        self.runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=self.sessions)

    async def create_session(self, user_id: str, state: dict) -> str:
        return (await self.sessions.create_session(app_name=APP_NAME, user_id=user_id, state=state)).id

    async def push_state(self, user_id: str, session_id: str, delta: dict) -> None:
        await _append_state(self.sessions, APP_NAME, user_id, session_id, delta)

    async def stream(self, user_id: str, session_id: str, message: str):
        from google.genai import types

        content = types.Content(role="user", parts=[types.Part(text=message)])
        async for ev in self.runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
            for b in blocks_from_event(ev.model_dump(mode="json", exclude_none=True)):
                yield b

    async def get_state(self, user_id: str, session_id: str) -> dict:
        s = await self.sessions.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
        return dict(s.state) if s else {}


class RemoteAgent:
    """The agent deployed on Agent Runtime. Needs roles/aiplatform.user."""

    def __init__(self, resource_name: str, project: str = "", location: str = "") -> None:
        from agentplatform import Client
        from google.adk.sessions import VertexAiSessionService

        parts = resource_name.split("/")            # projects/<p>/locations/<l>/reasoningEngines/<id>
        project = project or parts[1]
        location = location or parts[3]
        self.engine_id = parts[-1]
        self._rt = Client(project=project, location=location).runtimes.get(name=resource_name)
        self.sessions = VertexAiSessionService(project=project, location=location, agent_engine_id=self.engine_id)

    async def create_session(self, user_id: str, state: dict) -> str:
        return (await self.sessions.create_session(app_name=self.engine_id, user_id=user_id, state=state)).id

    async def push_state(self, user_id: str, session_id: str, delta: dict) -> None:
        await _append_state(self.sessions, self.engine_id, user_id, session_id, delta)

    async def stream(self, user_id: str, session_id: str, message: str):
        async for ev in self._rt.async_stream_query(user_id=user_id, session_id=session_id, message=message):
            ev = ev if isinstance(ev, dict) else ev.model_dump(mode="json", exclude_none=True)
            for b in blocks_from_event(ev):
                yield b

    async def get_state(self, user_id: str, session_id: str) -> dict:
        s = await self.sessions.get_session(app_name=self.engine_id, user_id=user_id, session_id=session_id)
        return dict(s.state) if s else {}


def make_agent(resource_name: str, project: str, location: str) -> AgentGateway:
    return RemoteAgent(resource_name, project, location) if resource_name else LocalAgent()
