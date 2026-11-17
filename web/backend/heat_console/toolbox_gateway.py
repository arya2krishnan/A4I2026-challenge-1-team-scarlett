"""The backend's only path to data: MCP Toolbox tools on the private Cloud Run service (ID-token auth).
The browser never talks to BigQuery or Toolbox."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol


class ToolInvoker(Protocol):
    async def invoke(self, name: str, params: dict) -> list[dict]: ...


def parse_rows(resp: Any) -> list[dict]:
    """Toolbox returns a JSON string (object, array or 'null'). Mirrors agent/heat_dispatch/results.py."""
    if resp is None:
        return []
    if isinstance(resp, str):
        text = resp.strip()
        if not text or text == "null":
            return []
        try:
            resp = json.loads(text)
        except ValueError:
            dec, i, rows = json.JSONDecoder(), 0, []
            while i < len(text):
                while i < len(text) and text[i] in " \r\n\t,":
                    i += 1
                if i >= len(text):
                    break
                obj, i = dec.raw_decode(text, i)
                rows.append(obj)
            return [r for r in rows if isinstance(r, dict)]
    if isinstance(resp, dict):
        for key in ("rows", "result", "results", "data"):
            if key in resp:
                return parse_rows(resp[key])
        return [resp]
    if isinstance(resp, list):
        return [r for r in resp if isinstance(r, dict)]
    return []


class ToolboxGateway:
    def __init__(self, url: str) -> None:
        self.url = url
        self._client = None
        self._tools: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    def _local(self) -> bool:
        return self.url.startswith(("http://127.0.0.1", "http://localhost"))

    async def _tool(self, name: str):
        async with self._lock:
            if self._client is None:
                from toolbox_core import ToolboxClient
                from toolbox_core.auth_methods import aget_google_id_token

                headers = {} if self._local() else {"Authorization": aget_google_id_token(self.url)}
                self._client = ToolboxClient(self.url, client_headers=headers)
            if name not in self._tools:
                self._tools[name] = await self._client.load_tool(name)
            return self._tools[name]

    async def invoke(self, name: str, params: dict) -> list[dict]:
        tool = await self._tool(name)
        return parse_rows(await tool(**params))

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
