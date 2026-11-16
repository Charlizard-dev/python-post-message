"""Platform registry. To add a platform: subclass ``Platform`` and list it here."""

from __future__ import annotations

import httpx

from app.config import Settings
from app.platforms.base import Platform, PlatformError, PostOutcome
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.discord import DiscordPlatform
from app.platforms.github_gist import GitHubGistPlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.telegram import TelegramPlatform
from app.platforms.telegraph import TelegraphPlatform

PLATFORM_CLASSES: list[type[Platform]] = [
    TelegraphPlatform,
    MastodonPlatform,
    BlueskyPlatform,
    TelegramPlatform,
    DiscordPlatform,
    GitHubGistPlatform,
]


def build_platforms(settings: Settings, client: httpx.AsyncClient) -> list[Platform]:
    return [cls(settings, client) for cls in PLATFORM_CLASSES]


__all__ = ["PLATFORM_CLASSES", "Platform", "PlatformError", "PostOutcome", "build_platforms"]
