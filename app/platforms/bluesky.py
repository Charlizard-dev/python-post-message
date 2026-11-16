"""Bluesky (AT Protocol) — https://docs.bsky.app/docs/advanced-guides/posts

1. ``com.atproto.server.createSession`` with handle + app password -> JWT
2. ``com.atproto.repo.createRecord`` with an ``app.bsky.feed.post`` record.

Links in Bluesky are *not* auto-detected: they must be declared as a
"facet" using UTF-8 **byte** offsets, which is done in :func:`link_facet`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.platforms.base import Platform, PlatformError, PostOutcome

PUBLIC_APPVIEW = "https://public.api.bsky.app"


class BlueskyPlatform(Platform):
    name = "Bluesky"
    docs_url = "https://docs.bsky.app/docs/advanced-guides/posts"

    def missing_config(self) -> list[str]:
        missing = []
        if not self.settings.bluesky_handle:
            missing.append("BLUESKY_HANDLE")
        if not self.settings.bluesky_app_password:
            missing.append("BLUESKY_APP_PASSWORD")
        return missing

    def secrets(self) -> list[str]:
        return [self.settings.bluesky_app_password or ""]

    async def publish(self, message: str, cta_url: str) -> PostOutcome:
        base = self.settings.bluesky_service.rstrip("/")
        session = (
            await self._request(
                "POST",
                f"{base}/xrpc/com.atproto.server.createSession",
                json={
                    "identifier": self.settings.bluesky_handle,
                    "password": self.settings.bluesky_app_password,
                },
            )
        ).json()

        now = datetime.now(timezone.utc)
        record: dict[str, Any] = {
            "$type": "app.bsky.feed.post",
            "text": message,
            "createdAt": now.isoformat().replace("+00:00", "Z"),
            "langs": ["en"],
        }
        facet = link_facet(message, cta_url)
        if facet:
            record["facets"] = [facet]

        created = (
            await self._request(
                "POST",
                f"{base}/xrpc/com.atproto.repo.createRecord",
                headers={"Authorization": f"Bearer {session['accessJwt']}"},
                json={"repo": session["did"], "collection": "app.bsky.feed.post", "record": record},
            )
        ).json()

        uri = created.get("uri")
        if not uri:
            raise PlatformError("Bluesky did not return a record URI")
        rkey = uri.rsplit("/", 1)[-1]
        handle = session.get("handle") or self.settings.bluesky_handle
        return PostOutcome(
            url=f"https://bsky.app/profile/{handle}/post/{rkey}",
            posted_at=now,
            extra={"uri": uri},
        )

    async def is_publicly_accessible(self, outcome: PostOutcome) -> bool:
        # bsky.app is a SPA that returns 200 for any path, so ask the public
        # (unauthenticated) AppView whether the post actually resolves.
        response = await self.client.get(
            f"{PUBLIC_APPVIEW}/xrpc/app.bsky.feed.getPosts",
            params={"uris": outcome.extra["uri"]},
        )
        return response.is_success and bool(response.json().get("posts"))


def link_facet(message: str, url: str) -> dict[str, Any] | None:
    index = message.find(url)
    if index < 0:
        return None
    start = len(message[:index].encode("utf-8"))
    return {
        "index": {"byteStart": start, "byteEnd": start + len(url.encode("utf-8"))},
        "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
    }
