"""Mastodon — https://docs.joinmastodon.org/methods/statuses/#create

Posts a public status. Uses the ``Idempotency-Key`` header so a retried
request can never produce a duplicate toot.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.platforms.base import Platform, PostOutcome


class MastodonPlatform(Platform):
    name = "Mastodon"
    docs_url = "https://docs.joinmastodon.org/methods/statuses/#create"

    def missing_config(self) -> list[str]:
        return [] if self.settings.mastodon_access_token else ["MASTODON_ACCESS_TOKEN"]

    def secrets(self) -> list[str]:
        return [self.settings.mastodon_access_token or ""]

    async def publish(self, message: str, cta_url: str) -> PostOutcome:
        response = await self._request(
            "POST",
            f"{self.settings.mastodon_base_url.rstrip('/')}/api/v1/statuses",
            headers={
                "Authorization": f"Bearer {self.settings.mastodon_access_token}",
                "Idempotency-Key": str(uuid.uuid4()),
            },
            data={"status": message, "visibility": "public"},
        )
        status = response.json()
        return PostOutcome(
            url=status.get("url") or status.get("uri"),
            posted_at=datetime.fromisoformat(status["created_at"].replace("Z", "+00:00")),
            extra={"id": status.get("id")},
        )
