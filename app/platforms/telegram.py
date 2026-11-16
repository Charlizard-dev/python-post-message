"""Telegram Bot API — https://core.telegram.org/bots/api#sendmessage

Sends the message to a channel/group where the bot is an admin. For public
channels (``@username``) the post gets a public ``https://t.me/<user>/<id>``
URL; private chats get a members-only ``t.me/c/...`` link.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.platforms.base import Platform, PlatformError, PostOutcome

API_BASE = "https://api.telegram.org"


class TelegramPlatform(Platform):
    name = "Telegram"
    docs_url = "https://core.telegram.org/bots/api#sendmessage"

    def missing_config(self) -> list[str]:
        missing = []
        if not self.settings.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.settings.telegram_chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        return missing

    def secrets(self) -> list[str]:
        return [self.settings.telegram_bot_token or ""]

    async def publish(self, message: str, cta_url: str) -> PostOutcome:
        # 4xx bodies look like {"ok": false, "description": "..."}; _request
        # surfaces "description" in the PlatformError.
        response = await self._request(
            "POST",
            f"{API_BASE}/bot{self.settings.telegram_bot_token}/sendMessage",
            json={
                "chat_id": self.settings.telegram_chat_id,
                "text": message,
                "link_preview_options": {"url": cta_url},
            },
        )
        body = response.json()
        if not body.get("ok"):
            raise PlatformError(f"Telegram error: {body.get('description', 'unknown error')}")

        result = body["result"]
        return PostOutcome(
            url=message_url(result),
            posted_at=datetime.fromtimestamp(result["date"], tz=timezone.utc),
            extra={"message_id": result["message_id"]},
        )


def message_url(result: dict[str, Any]) -> str | None:
    chat = result.get("chat", {})
    message_id = result["message_id"]
    if chat.get("username"):
        return f"https://t.me/{chat['username']}/{message_id}"
    chat_id = str(chat.get("id", ""))
    if chat_id.startswith("-100"):  # private supergroup/channel: members only
        return f"https://t.me/c/{chat_id[4:]}/{message_id}"
    return None
