"""Operator-constraint tools for the Heat Dispatch Console (web/).

The console backend writes `console_context` into the session state before each chat turn (plan version, day,
forecast, current constraints, approvals, skips, current item keys). The agent changes constraints with
`set_operator_constraints`, then `replan_dispatch` fetches fresh rankings from the MCP Toolbox (BigQuery ML runs
there), builds the plan with the deterministic planner and writes it, with a structured diff, to `console_plan`.
The backend reads `console_plan` from session state after the turn: the numbers never pass through model text.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from google.adk.tools import ToolContext

from . import planner
from .config import get_settings
from .dispatch import STATE_PARAMS, STATE_SITES, STATE_TRACTS
from .results import parse_rows

STATE_CTX = "console_context"           # written by the backend before each turn
STATE_CONSTRAINTS = "console_constraints"
STATE_PLAN = "console_plan"             # read by the backend after the turn
STATE_LIBS = "console_libraries"        # cached list_sites(category='Library') rows

Invoker = Callable[[str, dict], Awaitable[list[dict]]]


async def toolbox_invoke(name: str, params: dict) -> list[dict]:
    """Call one MCP Toolbox tool (ID-token auth when the server is the private Cloud Run service)."""
    from .toolbox import make_toolbox_client

    async with make_toolbox_client(get_settings()) as client:
        tool = await client.load_tool(name)
        return parse_rows(await tool(**params))


_invoke: Invoker = toolbox_invoke      # tests swap this for a fake


def _ctx(tool_context: Any) -> dict:
    return dict(tool_context.state.get(STATE_CTX) or {})


def _constraints(tool_context: Any) -> dict:
    cur = tool_context.state.get(STATE_CONSTRAINTS) or _ctx(tool_context).get("constraints")
    return planner.normalize_constraints(cur)


async def _libraries(tool_context: Any) -> list[dict]:
    libs = tool_context.state.get(STATE_LIBS)
    if not libs:
        libs = await _invoke("list_sites", {"category": "Library"})
        tool_context.state[STATE_LIBS] = libs
    return list(libs)


def get_dispatch_status(tool_context: ToolContext) -> dict:
    """Current dispatch console state: plan version, day, forecast, resources, cutoff, ranking, closed sites,
    approval status, and comprehensive coverage statistics (residents and seniors 65+ served).

    Args:
        tool_context: injected ADK ToolContext.
    """
    ctx = _ctx(tool_context)
    items = ctx.get("plan_items") or []
    summary = ctx.get("summary") or {}
    cov = ctx.get("coverage") or {}

    total_pop = cov.get("total_residents_covered") or sum(i.get("population") or 0 for i in items)
    total_65 = cov.get("total_seniors_65_plus_covered") or sum(i.get("seniors_65_plus") or 0 for i in items)
    pct_65 = round((summary.get("share_of_hot_65_plus_reached") or cov.get("share_of_hot_65_plus_reached") or 0.11) * 100)
    hot_tracts = summary.get("hot_tracts") or cov.get("hot_tracts") or 481
    hot_pop = summary.get("residents_in_hot_tracts") or cov.get("residents_in_hot_tracts") or 1670000

    return {
        "status": "ok",
        "plan_version": ctx.get("plan_version"),
        "day": ctx.get("weekday"),
        "forecast_high_f": ctx.get("forecast_high_f"),
        "constraints": _constraints(tool_context),
        "ranking_presets": planner.RANKING,
        "planned": {k: sum(1 for i in items if i.get("kind") == k) for k in planner.KINDS},
        "approved": len(ctx.get("approved") or {}),
        "skipped": len(ctx.get("skipped") or []),
        "coverage": {
            "share_of_hot_65_plus_reached_pct": f"{pct_65}%",
            "total_estimated_residents_served": total_pop,
            "total_seniors_65_plus_served": total_65,
            "hot_tracts_count": hot_tracts,
            "residents_in_hot_tracts": hot_pop,
            "by_intervention": {
                k: {
                    "count": sum(1 for i in items if i.get("kind") == k),
                    "residents_covered": sum(i.get("population") or 0 for i in items if i.get("kind") == k),
                    "seniors_65_plus_covered": sum(i.get("seniors_65_plus") or 0 for i in items if i.get("kind") == k),
                }
                for k in planner.KINDS
            },
        },
    }



async def set_operator_constraints(trucks: Optional[int] = None, wellness_teams: Optional[int] = None,
                                   libraries: Optional[int] = None, close_sites: Optional[list[str]] = None,
                                   reopen_sites: Optional[list[str]] = None, cutoff_f: Optional[float] = None,
                                   ranking: Optional[str] = None, tool_context: ToolContext = None) -> dict:
    """Change what the dispatch plan must respect. Pass ONLY what changed, as absolute values. Then call
    replan_dispatch.

    Args:
        trucks: hydration trucks available now (absolute count, 0-40).
        wellness_teams: wellness-check teams available now (absolute count, 0-40).
        libraries: library branches that can extend hours (absolute count, 0-20).
        close_sites: library branch names that cannot be used today (no power, closed, short-staffed).
        reopen_sites: library branch names that are available again.
        cutoff_f: hot cutoff, degrees F above the city average a place must reach to be considered (-3 to 3).
        ranking: 'balanced' (heat and vulnerability equally), 'heat' (heat only), or 'vulnerable' (vulnerability first).
        tool_context: injected ADK ToolContext.
    """
    before = _constraints(tool_context)
    c = dict(before)
    for k, v in (("trucks", trucks), ("wellness_teams", wellness_teams), ("libraries", libraries),
                 ("cutoff_f", cutoff_f)):
        if v is not None:
            c[k] = v
    if ranking is not None:
        if ranking not in planner.RANKING:
            return {"status": "error", "message": f"ranking must be one of {sorted(planner.RANKING)}"}
        c["ranking"] = ranking
    unknown: list[str] = []
    if close_sites or reopen_sites:
        names = [lb.get("site_name") for lb in await _libraries(tool_context) if lb.get("site_name")]
        closed = set(c["closed_sites"])
        hit, miss = planner.resolve_site_names(close_sites or [], names)
        closed |= set(hit)
        unknown += miss
        hit, miss = planner.resolve_site_names(reopen_sites or [], names)
        closed -= set(hit)
        unknown += miss
        c["closed_sites"] = sorted(closed)
    after = planner.normalize_constraints(c)
    tool_context.state[STATE_CONSTRAINTS] = after
    out: dict[str, Any] = {"status": "ok", "constraints": after, "changes": planner.constraint_changes(before, after)}
    if unknown:
        out["unknown_sites"] = unknown
        out["message"] = ("These names did not match exactly one Chicago Public Library branch: " + ", ".join(unknown)
                          + ". Ask the operator which branch they mean; only libraries affect the plan.")
    return out


async def replan_dispatch(tool_context: ToolContext) -> dict:
    """Rebuild the dispatch plan under the current constraints. Fetches fresh rankings (BigQuery ML runs live in the
    Toolbox), keeps approved items pinned, un-approves the lowest-priority ones if capacity dropped, and stores the new
    plan and its diff for the console. Returns a short summary to narrate; do not invent numbers beyond it.

    Args:
        tool_context: injected ADK ToolContext.
    """
    ctx = _ctx(tool_context)
    c = _constraints(tool_context)
    calls = planner.ranking_calls(c)
    try:
        sites = await _invoke("rank_priority_sites", calls["rank_priority_sites"])
        tracts = await _invoke("rank_wellness_check_tracts", calls["rank_wellness_check_tracts"])
        libs = await _libraries(tool_context)
    except Exception as exc:  # the console must say what failed, never guess
        return {"status": "error", "message": f"Could not reach the heat model tools ({exc.__class__.__name__}). "
                "The current plan is unchanged."}
    if not sites:
        return {"status": "need_data", "message": "The ranking returned no sites under these settings (cutoff too "
                "high?). The current plan is unchanged."}
    plan = planner.build_plan(c, sites, tracts, libs, approved=ctx.get("approved") or {},
                              skipped=ctx.get("skipped") or [], weekday=ctx.get("weekday") or "mon")
    diff = planner.diff_plans(ctx.get("plan_items") or [], plan["items"])
    changes = planner.constraint_changes(ctx.get("constraints"), c)
    tool_context.state[STATE_PLAN] = {"turn_id": ctx.get("turn_id"), "base_version": ctx.get("plan_version"),
                                      "plan": plan, "diff": diff, "changes": changes}
    # keep build_dispatch_plan working on the same rows
    tool_context.state[STATE_SITES] = sites
    tool_context.state[STATE_TRACTS] = tracts
    tool_context.state[STATE_PARAMS] = {k: v for k, v in calls["rank_priority_sites"].items()}
    return {
        "status": "ok", "changes": changes,
        "planned": {k: sum(1 for i in plan["items"] if i["kind"] == k) for k in planner.KINDS},
        "added": {k: [a["name"] for a in v["added"]] for k, v in diff.items()},
        "removed": {k: [a["name"] for a in v["removed"]] for k, v in diff.items()},
        "warnings": [w["message"] for w in plan["warnings"]],
        "note": "The console shows the new plan and its diff. Summarize in two or three sentences.",
    }
