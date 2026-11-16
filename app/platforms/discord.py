"""Discord webhooks — https://discord.com/developers/docs/resources/webhook#execute-webhook

``?wait=true`` makes Discord return the created message so we can build a
jump URL. ``allowed_mentions`` is emptied so user input can never trigger
@everyone / @here pings.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.platforms.base import Platform, PostOutcome


class DiscordPlatform(Platform):
    name = "Discord"
    docs_url = "https://discord.com/developers/docs/resources/webhook#execute-webhook"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._guild_id: str | None = None

    def missing_config(self) -> list[str]:
        return [] if self.settings.discord_webhook_url else ["DISCORD_WEBHOOK_URL"]

    def secrets(self) -> list[str]:
        return [self.settings.discord_webhook_url or ""]

    async def publish(self, message: str, cta_url: str) -> PostOutcome:
        webhook = self.settings.discord_webhook_url.rstrip("/")
        response = await self._request(
            "POST",
            webhook,
            params={"wait": "true"},
            json={"content": message, "allowed_mentions": {"parse": []}},
        )
        msg = response.json()

        guild_id = msg.get("guild_id") or await self._webhook_guild_id(webhook)
        url = (
            f"https://discord.com/channels/{guild_id}/{msg['channel_id']}/{msg['id']}"
            if guild_id
            else None
        )
        return PostOutcome(
            url=url,
            posted_at=datetime.fromisoformat(msg["timestamp"]),
            extra={"id": msg["id"]},
        )

    async def is_publicly_accessible(self, outcome: PostOutcome) -> bool:
        # Discord messages are only visible to logged-in server members.
        return False

    async def _webhook_guild_id(self, webhook: str) -> str | None:
        if self._guild_id is None:
            info = (await self._request("GET", webhook)).json()
            self._guild_id = info.get("guild_id")
        return self._guild_id
