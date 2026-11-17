"""Dispatch and operational action updates for Twitter / X threads."""
from __future__ import annotations

from typing import Any

from .twitter import TwitterClient, get_default_twitter_client, validate_and_truncate_tweet


def format_hydration_tweet(stop: dict, total_stops: int = 1) -> str:
    """Format an announcement for a deployed hydration truck (guaranteed <= 280 chars)."""
    neighborhood = stop.get("neighborhood") or "Chicago priority site"
    lat = stop.get("latitude", 0.0)
    lon = stop.get("longitude", 0.0)
    temp = stop.get("expected_air_temp_f", 0.0)
    stop_num = stop.get("stop", 1)

    temp_note = f"Expected air temp: {temp:.0f}°F. " if temp else ""
    loc_note = f"({lat:.4f}, {lon:.4f})"

    text = (
        f"🚛 ACTION TAKEN: Hydration Truck #{stop_num} deployed to {neighborhood} {loc_note}. "
        f"{temp_note}Free cold bottled water and cooling supplies available now. "
        f"Stay hydrated and avoid prolonged heat exposure! #ChiHeatAlert"
    )
    return validate_and_truncate_tweet(text)


def format_library_tweet(lib: dict) -> str:
    """Format an announcement for extended cooling center/library hours (<= 280 chars)."""
    name = lib.get("library") or "Chicago Public Library"
    addr = lib.get("address") or ""
    hours = lib.get("current_hours") or "Extended hours"

    text = (
        f"❄️ COOLING RELIEF UPDATE: Extended air-conditioned hours activated at {name} ({addr}). "
        f"Hours: {hours}. Free public air conditioning, seating, and water. "
        f"Call 311 to find all open cooling centers in Chicago. #BeatTheHeatChi"
    )
    return validate_and_truncate_tweet(text)


def format_wellness_tweet(teams: list[dict]) -> str:
    """Format an announcement for deployed wellness check teams (<= 280 chars)."""
    neighborhoods = [t.get("neighborhood") for t in teams if t.get("neighborhood")]
    unique_areas = list(dict.fromkeys(neighborhoods))[:4]
    area_str = ", ".join(unique_areas) if unique_areas else "high-vulnerability neighborhoods"

    text = (
        f"💜 WELLNESS TEAMS ACTIVE: Field teams are canvassing {area_str} checking on seniors "
        f"and vulnerable residents during extreme heat. "
        f"Know an elderly neighbor living alone? Request a free wellness check: dial 311 now. #ChiHeatAlert"
    )
    return validate_and_truncate_tweet(text)


def format_top_vulnerabilities_tweet(top_vulnerabilities: list[dict]) -> str:
    """Format an announcement identifying strictly the top 2 community vulnerabilities addressed (<= 280 chars)."""
    top2 = top_vulnerabilities[:2]
    if not top2:
        return "🎯 DISPATCH PRIORITIES: City resources deployed to mitigate acute urban heat risks. #ChiHeatAlert"

    v1 = top2[0].get("title", "Elderly residents without AC")
    v2 = top2[1].get("title", "Transit-dependent households") if len(top2) > 1 else "Heat-vulnerable households"

    text = (
        f"🎯 TOP 2 VULNERABILITIES IDENTIFIED:\n"
        f"1. {v1}\n"
        f"2. {v2}\n"
        f"City resources dispatched to mitigate these priority risks. #ChiHeatAlert #EquityInAction"
    )
    return validate_and_truncate_tweet(text)


def broadcast_dispatch_actions(
    dispatch_plan: dict[str, Any],
    root_tweet_id: str | None = None,
    client: TwitterClient | None = None,
) -> dict[str, Any]:
    """Tool: Publish Twitter updates for all operational dispatch actions taken.
    
    Identifies strictly the top 2 community vulnerabilities, drafts action tweets
    for each hydration truck stop, active wellness team area, and extended library cooling center,
    and replies to root_tweet_id so the public has a single, cohesive emergency thread.
    """
    from .vulnerability import identify_top_vulnerabilities

    cli = client or get_default_twitter_client()
    posted_updates: list[dict[str, Any]] = []
    current_reply_id = root_tweet_id

    # 1. Top 2 Identified Vulnerabilities Tweet
    top_vulns = identify_top_vulnerabilities(dispatch_plan=dispatch_plan, limit=2)
    vuln_tweet_text = format_top_vulnerabilities_tweet(top_vulns)
    res_vuln = cli.post(
        text=vuln_tweet_text,
        category="vulnerability_dispatch",
        reply_to_id=current_reply_id,
        metadata={"top_vulnerabilities": top_vulns},
    )
    posted_updates.append(res_vuln)
    if not current_reply_id:
        current_reply_id = res_vuln["tweet_id"]

    # 2. Hydration trucks deployed
    stops = dispatch_plan.get("hydration_stops") or []
    for s in stops:
        tweet_text = format_hydration_tweet(s, total_stops=len(stops))
        res = cli.post(
            text=tweet_text,
            category="hydration_dispatch",
            reply_to_id=current_reply_id,
            metadata={"stop": s.get("stop"), "neighborhood": s.get("neighborhood")},
        )
        posted_updates.append(res)
        # Chain subsequent tweets or keep replying to root
        if not current_reply_id:
            current_reply_id = res["tweet_id"]

    # 2. Library cooling extensions
    libraries = dispatch_plan.get("library_extensions") or []
    for lib in libraries:
        tweet_text = format_library_tweet(lib)
        res = cli.post(
            text=tweet_text,
            category="library_dispatch",
            reply_to_id=current_reply_id,
            metadata={"library": lib.get("library")},
        )
        posted_updates.append(res)

    # 3. Wellness check teams
    teams = dispatch_plan.get("wellness_teams") or []
    if teams:
        tweet_text = format_wellness_tweet(teams)
        res = cli.post(
            text=tweet_text,
            category="wellness_dispatch",
            reply_to_id=current_reply_id,
            metadata={"team_count": len(teams)},
        )
        posted_updates.append(res)

    return {
        "status": "ok",
        "action_tweets_count": len(posted_updates),
        "top_2_vulnerabilities": top_vulns,
        "updates": posted_updates,
        "root_tweet_id": root_tweet_id,
        "summary": f"Broadcasted {len(posted_updates)} operational action update(s) to Twitter.",
    }
