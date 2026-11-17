# agent/

`heat_dispatch/` is the ADK agent (root agent in `agent.py`). It reaches BigQuery only through the MCP Toolbox server
(`toolbox/tools.yaml`) and has a few Python tools for work that is not a single query.

| File | What it holds |
|---|---|
| `agent.py` | root agent, the after-tool callback that stores ranked rows in session state, the out-of-Chicago guard |
| `prompts.py` | system instruction: which tool for which question, and when to refuse |
| `toolbox.py` | `ToolboxToolset` connection (plain HTTP locally; Cloud Run ID-token auth when deployed) |
| `dispatch.py` | `build_dispatch_plan`: builds the dispatch sheet from stored tool output |
| `forecast.py` / `places.py` / `narration.py` / `results.py` | NWS forecast + heat index, place lookup, attribution wording, result parsing |

Design and limits: `../docs/ARCHITECTURE.md`. Steps to run and deploy: `../docs/RUNBOOK.md`.
