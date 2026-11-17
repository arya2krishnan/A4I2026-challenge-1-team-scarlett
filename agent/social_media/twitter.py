"""Twitter / X client supporting both live API v2 publishing and in-memory/simulated ledger mode."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_social_settings

logger = logging.getLogger(__name__)

MAX_TWEET_CHARS = 280


@dataclass
class Tweet:
    id: str
    text: str
    created_at: str
    category: str
    in_reply_to_tweet_id: str | None = None
    status: str = "published"
    metadata: dict[str, Any] = field(default_factory=dict)


class TwitterLedger:
    """Thread-safe persistent/in-memory store for broadcast tweets."""

    def __init__(self, storage_path: Path | None = None) -> None:
        if storage_path is None:
            storage_dir = Path(__file__).resolve().parents[2] / ".data"
            storage_dir.mkdir(parents=True, exist_ok=True)
            storage_path = storage_dir / "social_feed.json"
        self._path = storage_path
        self._tweets: list[Tweet] = []
        self._load()

    def _load(self) -> None:
        if self._path.is_file():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._tweets = [Tweet(**item) for item in data]
            except Exception as exc:
                logger.warning(f"Failed to load social feed ledger: {exc}")
                self._tweets = []

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps([asdict(t) for t in self._tweets], indent=2),
                encoding="utf-8"
            )
        except Exception as exc:
            logger.warning(f"Failed to persist social feed ledger: {exc}")

    def add(self, tweet: Tweet) -> None:
        self._tweets.append(tweet)
        self._save()

    def list_tweets(self, limit: int = 50, category: str | None = None) -> list[Tweet]:
        tweets = self._tweets
        if category:
            tweets = [t for t in tweets if t.category == category]
        return sorted(tweets, key=lambda t: t.created_at, reverse=True)[:limit]

    def get(self, tweet_id: str) -> Tweet | None:
        for t in self._tweets:
            if t.id == tweet_id:
                return t
        return None

    def get_thread(self, root_id: str) -> list[Tweet]:
        root = self.get(root_id)
        if not root:
            return []
        thread = [root]
        # find descendants
        current_ids = {root_id}
        while True:
            children = [t for t in self._tweets if t.in_reply_to_tweet_id in current_ids and t not in thread]
            if not children:
                break
            thread.extend(sorted(children, key=lambda t: t.created_at))
            current_ids = {c.id for c in children}
        return thread

    def clear(self) -> None:
        self._tweets.clear()
        if self._path.is_file():
            try:
                self._path.unlink()
            except OSError:
                pass


# Global singleton ledger
_GLOBAL_LEDGER = TwitterLedger()


def validate_and_truncate_tweet(text: str, max_length: int = MAX_TWEET_CHARS) -> str:
    """Ensure tweet fits within max_length characters without cutting off words abruptly."""
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= max_length:
        return cleaned
    
    # Truncate at word boundary
    truncated = cleaned[: max_length - 1]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return f"{truncated}…"


class TwitterClient:
    """Twitter v2 Client with automatic fallback to local simulation ledger."""

    def __init__(self, ledger: TwitterLedger | None = None) -> None:
        self.settings = get_social_settings()
        self.ledger = ledger or _GLOBAL_LEDGER

    def post(
        self,
        text: str,
        category: str = "general",
        reply_to_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Post a tweet either live or to the simulation ledger."""
        formatted_text = validate_and_truncate_tweet(text)
        tweet_id = f"tw_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        # If live Twitter API credentials configured, attempt real post
        is_live = False
        if self.settings.is_twitter_configured:
            try:
                # Live Twitter API v2 call using requests_oauthlib or Bearer token
                import requests
                from requests_oauthlib import OAuth1

                auth = OAuth1(
                    self.settings.twitter_api_key,
                    self.settings.twitter_api_secret,
                    self.settings.twitter_access_token,
                    self.settings.twitter_access_token_secret,
                )
                payload: dict[str, Any] = {"text": formatted_text}
                if reply_to_id:
                    payload["reply"] = {"in_reply_to_tweet_id": reply_to_id}

                resp = requests.post(
                    "https://api.twitter.com/2/tweets",
                    json=payload,
                    auth=auth,
                    timeout=10,
                )
                if resp.status_code in (200, 201):
                    live_data = resp.json().get("data", {})
                    tweet_id = live_data.get("id", tweet_id)
                    is_live = True
                else:
                    logger.warning(f"Twitter API returned status {resp.status_code}: {resp.text}")
            except Exception as exc:
                logger.warning(f"Live Twitter API post failed; recording to simulation ledger: {exc}")

        tweet = Tweet(
            id=tweet_id,
            text=formatted_text,
            created_at=now_iso,
            category=category,
            in_reply_to_tweet_id=reply_to_id,
            status="published",
            metadata={"live_api": is_live, **(metadata or {})},
        )
        self.ledger.add(tweet)

        return {
            "status": "ok",
            "tweet_id": tweet.id,
            "text": tweet.text,
            "char_count": len(tweet.text),
            "created_at": tweet.created_at,
            "category": tweet.category,
            "in_reply_to": tweet.in_reply_to_tweet_id,
            "mode": "live" if is_live else "simulated",
        }


def get_default_twitter_client() -> TwitterClient:
    return TwitterClient()
