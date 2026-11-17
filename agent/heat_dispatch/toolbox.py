"""Connect the agent to the MCP Toolbox server (the managed MCP layer in front of BigQuery).

Locally the server is plain HTTP on 127.0.0.1. Deployed, it is a private Cloud Run service: the agent presents a
Google-signed ID token for that service (audience = its URL) using its own identity, so only this agent can call it.

Event loops: Agent Runtime runs every query on a NEW asyncio event loop, but ToolboxToolset keeps an aiohttp session
bound to the loop it was first used on. From the second query on, loading the tools raised "Event loop is closed", the
model silently had no data tools, and it told users the ranking tools were "unavailable". LoopSafeToolboxToolset keeps
one client per event loop instead, so every query gets a live session.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Optional

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from toolbox_adk import CredentialStrategy, ToolboxToolset

from .config import Settings


def is_local(url: str) -> bool:
    return url.startswith("http://127.0.0.1") or url.startswith("http://localhost")


class LoopSafeToolboxToolset(BaseToolset):
    """A ToolboxToolset per running event loop; toolsets whose loop has closed are dropped."""

    def __init__(self, factory: Callable[[], BaseToolset], **kwargs) -> None:
        super().__init__(**kwargs)
        self._factory = factory
        self._by_loop: dict[asyncio.AbstractEventLoop, BaseToolset] = {}

    def _current(self) -> BaseToolset:
        loop = asyncio.get_running_loop()
        for dead in [l for l in self._by_loop if l.is_closed()]:
            self._by_loop.pop(dead)          # their sessions died with the loop; nothing left to close
        if loop not in self._by_loop:
            self._by_loop[loop] = self._factory()
        return self._by_loop[loop]

    async def get_tools(self, readonly_context: Optional[ReadonlyContext] = None) -> list[BaseTool]:
        return await self._current().get_tools(readonly_context)

    async def close(self) -> None:
        for loop, ts in list(self._by_loop.items()):
            if not loop.is_closed():
                try:
                    await ts.close()
                except Exception:
                    pass
        self._by_loop.clear()


def build_toolbox_toolset(settings: Settings) -> LoopSafeToolboxToolset:
    def make() -> ToolboxToolset:
        credentials = None if is_local(settings.toolbox_url) else CredentialStrategy.workload_identity(
            target_audience=settings.toolbox_url)
        return ToolboxToolset(server_url=settings.toolbox_url, toolset_name=settings.toolbox_toolset,
                              credentials=credentials)

    return LoopSafeToolboxToolset(make)


def make_toolbox_client(settings: Settings):
    """A plain toolbox_core client for Python tools that call Toolbox directly (e.g. replan_dispatch).

    Safe across event loops ONLY because callers open it per call (`async with make_toolbox_client(...)`); never cache it.
    """
    from toolbox_core import ToolboxClient
    from toolbox_core.auth_methods import aget_google_id_token

    headers = {} if is_local(settings.toolbox_url) else {"Authorization": aget_google_id_token(settings.toolbox_url)}
    return ToolboxClient(settings.toolbox_url, client_headers=headers)
