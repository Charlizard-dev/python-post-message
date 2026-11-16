"""Common contract and HTTP plumbing shared by every platform integration."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# Only retry when we know the platform did NOT act on the request, so a retry
# can never create a duplicate post:
#   * connection could not be established / timed out before sending
#   * 429 Too Many Requests / 503 Service Unavailable (request rejected)
RETRYABLE_EXCEPTIONS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
RETRYABLE_STATUS = {429, 503}
MAX_RETRY_AFTER = 5.0


class PlatformError(Exception):
    """A clean, user-facing failure reported by (or about) a platform."""


@dataclass
class PostOutcome:
    """What a platform returns after a successful publish."""

    url: str | None
    posted_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Platform(ABC):
    name: ClassVar[str]
    docs_url: ClassVar[str]

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client

    # ------------------------------------------------------------------ API
    @abstractmethod
    def missing_config(self) -> list[str]:
        """Names of required env vars that are not set (empty == ready)."""

    @abstractmethod
    async def publish(self, message: str, cta_url: str) -> PostOutcome:
        """Publish ``message``; raise :class:`PlatformError` on failure."""

    def secrets(self) -> list[str]:
        """Configured secret values, redacted from any error message."""
        return []

    async def is_publicly_accessible(self, outcome: PostOutcome) -> bool:
        """Default check: anonymous GET of the posted URL returns 2xx."""
        if not outcome.url:
            return False
        response = await self.client.get(outcome.url, follow_redirects=True)
        return response.is_success

    # -------------------------------------------------------------- helpers
    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send a request with safe retries and turn HTTP errors into PlatformError."""
        attempt = 0
        while True:
            try:
                response = await self.client.request(method, url, **kwargs)
            except RETRYABLE_EXCEPTIONS as exc:
                if attempt >= self.settings.max_retries:
                    raise PlatformError(f"Network error: {type(exc).__name__}") from exc
                await self._backoff(attempt, None)
            except httpx.TimeoutException as exc:
                # Read/write timeout: the post MAY have been created -> never retry.
                raise PlatformError(
                    f"Timed out waiting for {self.name} ({type(exc).__name__})"
                ) from exc
            except httpx.HTTPError as exc:
                raise PlatformError(f"HTTP error: {type(exc).__name__}") from exc
            else:
                if response.status_code in RETRYABLE_STATUS and attempt < self.settings.max_retries:
                    await self._backoff(attempt, response.headers.get("Retry-After"))
                elif response.is_error:
                    raise PlatformError(
                        f"HTTP {response.status_code}: {self._error_detail(response)}"
                    )
                else:
                    return response
            attempt += 1
            logger.warning("%s: retrying request (attempt %d)", self.name, attempt + 1)

    async def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = 0.5 * (2**attempt)
        if retry_after:
            try:
                delay = min(float(retry_after), MAX_RETRY_AFTER)
            except ValueError:
                pass
        await asyncio.sleep(delay)

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """Best-effort extraction of a readable error from an API response."""
        try:
            body = response.json()
        except ValueError:
            return response.text[:200] or response.reason_phrase
        if isinstance(body, dict):
            parts = [
                str(body[key])
                for key in ("error", "message", "description", "error_description")
                if body.get(key) and isinstance(body[key], (str, int))
            ]
            if parts:
                return ": ".join(dict.fromkeys(parts))
        return str(body)[:200]


def split_on_link(message: str, url: str) -> tuple[str, str]:
    """Split ``message`` into the text before and after the CTA link."""
    index = message.find(url)
    if index < 0:
        return message, ""
    return message[:index], message[index + len(url):]


def title_from_message(message: str, url: str, limit: int = 80) -> str:
    """Derive a short title from the message text (without the link)."""
    before, after = split_on_link(message, url)
    text = " ".join(f"{before} {after}".split()) or "Announcement"
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
