from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from app.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        max_retries=1,
        platform_timeout=2,
        telegraph_enabled=True,
        mastodon_access_token="mastodon-secret-token",
        bluesky_handle="tester.bsky.social",
        bluesky_app_password="abcd-efgh-ijkl-mnop",
        telegram_bot_token="123456:TELEGRAM-SECRET",
        telegram_chat_id="@my_channel",
        discord_webhook_url="https://discord.com/api/webhooks/111/DISCORD-SECRET",
        github_token="ghp_github_secret_token",
    )


Handler = Callable[[httpx.Request], httpx.Response]


def run(coro):
    return asyncio.run(coro)


def mock_client(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def body_json(request: httpx.Request) -> dict:
    return json.loads(request.content)
