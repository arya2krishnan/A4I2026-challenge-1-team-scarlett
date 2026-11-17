"""Settings and configuration for Social Media & 311 Heat Emergency communications."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).resolve().parent
for _env in (_HERE / ".env", *(p / ".env" for p in _HERE.parents[:3])):
    if _env.is_file():
        load_dotenv(_env, override=False)


def _s(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class SocialMediaSettings:
    twitter_api_key: str
    twitter_api_secret: str
    twitter_access_token: str
    twitter_access_token_secret: str
    twitter_bearer_token: str
    critical_threshold_f: float
    critical_heat_index_threshold_f: float
    auto_broadcast: bool
    city_name: str
    default_hashtags: str

    @property
    def is_twitter_configured(self) -> bool:
        return bool(self.twitter_api_key and self.twitter_access_token) or bool(self.twitter_bearer_token)


def get_social_settings() -> SocialMediaSettings:
    return SocialMediaSettings(
        twitter_api_key=_s("TWITTER_API_KEY"),
        twitter_api_secret=_s("TWITTER_API_SECRET"),
        twitter_access_token=_s("TWITTER_ACCESS_TOKEN"),
        twitter_access_token_secret=_s("TWITTER_ACCESS_TOKEN_SECRET"),
        twitter_bearer_token=_s("TWITTER_BEARER_TOKEN"),
        critical_threshold_f=_f("CRITICAL_HEAT_THRESHOLD_F", 95.0),
        critical_heat_index_threshold_f=_f("CRITICAL_HEAT_INDEX_THRESHOLD_F", 100.0),
        auto_broadcast=os.environ.get("AUTO_BROADCAST", "").lower() in ("1", "true", "yes"),
        city_name=_s("CITY_NAME", "Chicago"),
        default_hashtags=_s("DEFAULT_HASHTAGS", "#ChiHeatAlert #BeatTheHeatChi #ChicagoCooling"),
    )
