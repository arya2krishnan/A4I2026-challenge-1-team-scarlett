"""Connect the agent to the MCP Toolbox server (the managed MCP layer in front of BigQuery).

Locally the server is plain HTTP on 127.0.0.1. Deployed, it is a private Cloud Run service: the agent presents a
Google-signed ID token for that service (audience = its URL) using its own identity, so only this agent can call it.
"""
from __future__ import annotations

from toolbox_adk import CredentialStrategy, ToolboxToolset

from .config import Settings


def is_local(url: str) -> bool:
    return url.startswith("http://127.0.0.1") or url.startswith("http://localhost")


def build_toolbox_toolset(settings: Settings) -> ToolboxToolset:
    credentials = None if is_local(settings.toolbox_url) else CredentialStrategy.workload_identity(
        target_audience=settings.toolbox_url)
    return ToolboxToolset(server_url=settings.toolbox_url, toolset_name=settings.toolbox_toolset,
                          credentials=credentials)


def make_toolbox_client(settings: Settings):
    """A plain toolbox_core client (used by Python tools that call Toolbox directly, e.g. replan_dispatch)."""
    from toolbox_core import ToolboxClient
    from toolbox_core.auth_methods import aget_google_id_token

    headers = {} if is_local(settings.toolbox_url) else {"Authorization": aget_google_id_token(settings.toolbox_url)}
    return ToolboxClient(settings.toolbox_url, client_headers=headers)
