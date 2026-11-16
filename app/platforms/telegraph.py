"""Telegraph (telegra.ph) — https://telegra.ph/api

Anonymous publishing platform by Telegram. Requires no sign-up: if no
``TELEGRAPH_ACCESS_TOKEN`` is configured an account is created on the fly via
``createAccount`` and reused for the lifetime of the process.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.platforms.base import Platform, PlatformError, PostOutcome, split_on_link, title_from_message

API_BASE = "https://api.telegra.ph"


class TelegraphPlatform(Platform):
    name = "Telegraph"
    docs_url = "https://telegra.ph/api"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._token: str | None = self.settings.telegraph_access_token
        self._token_lock = asyncio.Lock()

    def missing_config(self) -> list[str]:
        return [] if self.settings.telegraph_enabled else ["TELEGRAPH_ENABLED=true"]

    def secrets(self) -> list[str]:
        return [self._token] if self._token else []

    async def publish(self, message: str, cta_url: str) -> PostOutcome:
        token = await self._access_token()
        result = await self._call(
            "createPage",
            {
                "access_token": token,
                "title": title_from_message(message, cta_url),
                "author_name": self.settings.telegraph_author_name,
                "content": json.dumps(build_content(message, cta_url), ensure_ascii=False),
                "return_content": "false",
            },
        )
        return PostOutcome(url=result["url"], extra={"path": result.get("path")})

    async def _access_token(self) -> str:
        async with self._token_lock:
            if not self._token:
                account = await self._call(
                    "createAccount",
                    {
                        "short_name": self.settings.telegraph_short_name,
                        "author_name": self.settings.telegraph_author_name,
                    },
                )
                self._token = account["access_token"]
            return self._token

    async def _call(self, method: str, data: dict[str, str]) -> dict[str, Any]:
        response = await self._request("POST", f"{API_BASE}/{method}", data=data)
        body = response.json()
        if not body.get("ok"):
            raise PlatformError(f"Telegraph {method} failed: {body.get('error', 'unknown error')}")
        return body["result"]


def build_content(message: str, cta_url: str) -> list[dict[str, Any]]:
    """Telegraph Node array: one paragraph with the CTA rendered as a link."""
    before, after = split_on_link(message, cta_url)
    children: list[Any] = [part for part in (before,) if part]
    children.append({"tag": "a", "attrs": {"href": cta_url}, "children": [cta_url]})
    if after:
        children.append(after)
    return [{"tag": "p", "children": children}]
