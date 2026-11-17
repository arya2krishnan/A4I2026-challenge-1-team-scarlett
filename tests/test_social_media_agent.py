"""Unit tests for the Social Media Twitter/X broadcast agent."""
from __future__ import annotations

import pytest

from social_media.alerts import broadcast_critical_alert, build_critical_alert_text, is_heat_critical
from social_media.config import SocialMediaSettings, get_social_settings
from social_media.dispatch_updates import (
    broadcast_dispatch_actions,
    format_hydration_tweet,
    format_library_tweet,
    format_wellness_tweet,
)
from social_media.twitter import (
    MAX_TWEET_CHARS,
    TwitterClient,
    TwitterLedger,
    validate_and_truncate_tweet,
)


@pytest.fixture
def clean_client(tmp_path):
    ledger = TwitterLedger(storage_path=tmp_path / "test_feed.json")
    return TwitterClient(ledger=ledger)


def test_validate_and_truncate_tweet_enforces_280_chars():
    short_text = "This is a short heat advisory."
    assert validate_and_truncate_tweet(short_text) == short_text

    long_text = "Word " * 70  # 350 chars
    truncated = validate_and_truncate_tweet(long_text)
    assert len(truncated) <= MAX_TWEET_CHARS
    assert truncated.endswith("…")


def test_is_heat_critical():
    assert is_heat_critical(95.0) is True
    assert is_heat_critical(102.0) is True
    assert is_heat_critical(91.0) is False
    assert is_heat_critical(91.0, heat_index_f=103.0) is True


def test_build_critical_alert_text_format_and_length():
    alert = build_critical_alert_text(
        forecast_high_f=102.0,
        hotspots=["Englewood", "Back of the Yards", "Humboldt Park"],
        heat_index_f=108.0,
    )
    assert len(alert) <= MAX_TWEET_CHARS
    assert "102°F" in alert
    assert "Englewood" in alert
    assert "911" in alert
    assert "311" in alert
    assert "#ChiHeatAlert" in alert


def test_broadcast_critical_alert_creates_thread(clean_client):
    res = broadcast_critical_alert(
        forecast_high_f=102.0,
        hotspots=["Englewood", "Humboldt Park"],
        client=clean_client,
    )
    assert res["status"] == "ok"
    assert res["is_critical"] is True
    root_id = res["root_tweet_id"]
    assert root_id is not None
    assert len(res["tweets_posted"]) == 2

    # Second tweet replies to root
    assert res["tweets_posted"][0]["in_reply_to"] is None
    assert res["tweets_posted"][1]["in_reply_to"] == root_id

    # Verify thread structure in ledger
    thread = clean_client.ledger.get_thread(root_id)
    assert len(thread) == 2
    assert thread[0].id == root_id


def test_format_action_tweets_within_character_limit():
    stop = {
        "stop": 1,
        "neighborhood": "Englewood",
        "latitude": 41.77961,
        "longitude": -87.64439,
        "expected_air_temp_f": 108.1,
    }
    h_tweet = format_hydration_tweet(stop)
    assert len(h_tweet) <= MAX_TWEET_CHARS
    assert "Hydration Truck #1" in h_tweet
    assert "Englewood" in h_tweet

    lib = {
        "library": "Sherman Park Library",
        "address": "5440 S Racine Ave",
        "current_hours": "Extended to 8:00 PM",
    }
    l_tweet = format_library_tweet(lib)
    assert len(l_tweet) <= MAX_TWEET_CHARS
    assert "Sherman Park Library" in l_tweet

    teams = [
        {"team": 1, "neighborhood": "West Englewood"},
        {"team": 2, "neighborhood": "North Lawndale"},
    ]
    w_tweet = format_wellness_tweet(teams)
    assert len(w_tweet) <= MAX_TWEET_CHARS
    assert "West Englewood" in w_tweet


def test_format_top_vulnerabilities_tweet_strictly_two():
    from social_media.dispatch_updates import format_top_vulnerabilities_tweet
    sample_vulns = [
        {"title": "Elderly seniors (65+) living without AC", "score": 45},
        {"title": "Transit-dependent households without vehicles", "score": 35},
        {"title": "Third ignored vulnerability", "score": 10},
    ]
    tweet = format_top_vulnerabilities_tweet(sample_vulns)
    assert len(tweet) <= MAX_TWEET_CHARS
    assert "TOP 2 VULNERABILITIES IDENTIFIED" in tweet
    assert "1. Elderly seniors" in tweet
    assert "2. Transit-dependent" in tweet
    assert "Third ignored" not in tweet  # Strictly top 2!


def test_broadcast_dispatch_actions_chains_to_root(clean_client):
    # Post root alert first
    alert_res = broadcast_critical_alert(forecast_high_f=100.0, client=clean_client)
    root_id = alert_res["root_tweet_id"]

    sample_plan = {
        "hydration_stops": [
            {"stop": 1, "neighborhood": "Englewood", "latitude": 41.7796, "longitude": -87.6444, "expected_air_temp_f": 105.0},
            {"stop": 2, "neighborhood": "Humboldt Park", "latitude": 41.9022, "longitude": -87.7211, "expected_air_temp_f": 103.5},
        ],
        "library_extensions": [
            {"library": "Sherman Park", "address": "5440 S Racine Ave", "current_hours": "Extended until 8pm"},
        ],
        "wellness_teams": [
            {"team": 1, "neighborhood": "Englewood"},
            {"team": 2, "neighborhood": "East Garfield Park"},
        ],
    }

    dispatch_res = broadcast_dispatch_actions(
        dispatch_plan=sample_plan,
        root_tweet_id=root_id,
        client=clean_client,
    )

    assert dispatch_res["status"] == "ok"
    # 1 top-2-vulnerabilities + 2 hydration + 1 library + 1 wellness = 5 updates
    assert dispatch_res["action_tweets_count"] == 5
    assert len(dispatch_res["top_2_vulnerabilities"]) == 2
    for u in dispatch_res["updates"]:
        assert len(u["text"]) <= MAX_TWEET_CHARS

    # The entire thread should have root + 1 alert tip + 5 dispatch updates = 7 tweets
    full_thread = clean_client.ledger.get_thread(root_id)
    assert len(full_thread) == 7
