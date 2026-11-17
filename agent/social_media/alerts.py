"""Critical heat emergency alerts generation and posting for Twitter / X."""
from __future__ import annotations

from typing import Any

from .config import get_social_settings
from .twitter import MAX_TWEET_CHARS, TwitterClient, get_default_twitter_client, validate_and_truncate_tweet


def is_heat_critical(forecast_high_f: float, heat_index_f: float | None = None) -> bool:
    """Evaluate if conditions meet the critical heat threshold for Chicago."""
    settings = get_social_settings()
    if forecast_high_f >= settings.critical_threshold_f:
        return True
    if heat_index_f is not None and heat_index_f >= settings.critical_heat_index_threshold_f:
        return True
    return False


def build_critical_alert_text(
    forecast_high_f: float,
    hotspots: list[str] | None = None,
    heat_index_f: float | None = None,
) -> str:
    """Format the primary emergency alert tweet (guaranteed <= 280 characters)."""
    temp_str = f"{forecast_high_f:.0f}°F"
    if heat_index_f:
        temp_str += f" (Heat Index {heat_index_f:.0f}°F)"

    footer = " Need AC? Call 311 for nearest cooling center. Emergencies: 911. #ChiHeatAlert"
    base = f"🚨 HEAT EMERGENCY ALERT: Chicago forecast high is {temp_str}."

    hotspot_str = ""
    if hotspots:
        top_areas = ", ".join(hotspots[:2])
        hotspot_str = f" High-risk: {top_areas}."

    advice = " Stay indoors, hydrate, check on elderly neighbors."

    # Try full message
    msg = f"{base}{hotspot_str}{advice}{footer}"
    if len(msg) <= MAX_TWEET_CHARS:
        return msg

    # Shorten advice if needed
    msg = f"{base}{hotspot_str} Stay hydrated and cool.{footer}"
    if len(msg) <= MAX_TWEET_CHARS:
        return msg

    # Fallback minimal with guaranteed footer
    max_base = MAX_TWEET_CHARS - len(footer)
    return f"{base[:max_base]}{footer}"


def build_advisory_thread(
    forecast_high_f: float,
    hotspots: list[str] | None = None,
) -> list[str]:
    """Generate a multi-tweet advisory thread if full safety guidance is needed."""
    tweets = []
    # Tweet 1: Alert & Hotline
    tweets.append(build_critical_alert_text(forecast_high_f, hotspots))

    # Tweet 2: Public Safety & Vulnerable Populations
    t2 = (
        "⚠️ HEAT SAFETY TIPS: Limit outdoor activity 11am-4pm. Never leave kids/pets in cars. "
        "Symptoms of heat stroke (hot/dry skin, confusion) are life-threatening—dial 911 immediately. "
        "Free air-conditioned libraries and cooling centers are open citywide: call 311. #BeatTheHeatChi"
    )
    tweets.append(validate_and_truncate_tweet(t2))

    return tweets


def broadcast_critical_alert(
    forecast_high_f: float,
    hotspots: list[str] | None = None,
    heat_index_f: float | None = None,
    client: TwitterClient | None = None,
) -> dict[str, Any]:
    """Tool: Broadcast a critical heat alert to Twitter/X.
    
    If the weather reaches emergency thresholds (>= 95°F), this posts an official
    emergency advisory thread and returns the root tweet ID for dispatch updates.
    """
    cli = client or get_default_twitter_client()
    critical = is_heat_critical(forecast_high_f, heat_index_f)
    
    thread_texts = build_advisory_thread(forecast_high_f, hotspots)
    posted_tweets = []
    parent_id = None

    for i, text in enumerate(thread_texts):
        result = cli.post(
            text=text,
            category="critical_alert",
            reply_to_id=parent_id,
            metadata={
                "forecast_high_f": forecast_high_f,
                "heat_index_f": heat_index_f,
                "is_critical": critical,
                "hotspots": hotspots or [],
                "thread_index": i + 1,
            },
        )
        posted_tweets.append(result)
        if parent_id is None:
            parent_id = result["tweet_id"]

    return {
        "status": "ok",
        "is_critical": critical,
        "root_tweet_id": parent_id,
        "tweets_posted": posted_tweets,
        "summary": f"Posted {len(posted_tweets)} alert tweet(s). Root Tweet ID: {parent_id}",
    }
