"""Fan-out orchestration: publish to every platform concurrently, isolating
failures so one broken integration never affects the others."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from app.config import Settings
from app.platforms.base import Platform, PlatformError
from app.schemas import PlatformResult, PostStatus

logger = logging.getLogger(__name__)


class PostingService:
    def __init__(self, platforms: list[Platform], settings: Settings) -> None:
        self.platforms = platforms
        self.settings = settings

    async def post_everywhere(self, message: str, cta_url: str) -> list[PlatformResult]:
        # _post_one never raises, so gather() always returns one result per
        # platform, in registry order.
        return list(
            await asyncio.gather(*(self._post_one(p, message, cta_url) for p in self.platforms))
        )

    async def _post_one(self, platform: Platform, message: str, cta_url: str) -> PlatformResult:
        missing = platform.missing_config()
        if missing:
            logger.info("%s: skipped (not configured: %s)", platform.name, ", ".join(missing))
            return _failed(platform, f"Platform not configured. Set: {', '.join(missing)}")

        started = time.perf_counter()
        try:
            outcome = await asyncio.wait_for(
                platform.publish(message, cta_url), timeout=self.settings.platform_timeout
            )
        except PlatformError as exc:
            error = _redact(str(exc), platform.secrets())
            logger.warning("%s: failed - %s", platform.name, error)
            return _failed(platform, error)
        except asyncio.TimeoutError:
            error = f"Timed out after {self.settings.platform_timeout:g}s"
            logger.warning("%s: failed - %s", platform.name, error)
            return _failed(platform, error)
        except Exception as exc:  # defensive: a bug in one integration must not kill the batch
            logger.exception("%s: unexpected error", platform.name)
            return _failed(platform, f"Unexpected error: {type(exc).__name__}")

        posted_at = (outcome.posted_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        public = await self._check_public(platform, outcome)
        logger.info(
            "%s: posted in %.2fs -> %s (public=%s)",
            platform.name, time.perf_counter() - started, outcome.url, public,
        )
        return PlatformResult(
            platform=platform.name,
            status=PostStatus.SUCCESS,
            posted_url=outcome.url,
            public_access=public,
            date=posted_at.strftime("%Y-%m-%d"),
            time=posted_at.strftime("%H:%M:%S"),
            error=None,
        )

    async def _check_public(self, platform: Platform, outcome) -> bool:
        if not self.settings.verify_public_access or not outcome.url:
            return False
        try:
            return await platform.is_publicly_accessible(outcome)
        except Exception as exc:  # a failed check must not turn a success into a failure
            logger.info("%s: public-access check failed (%s)", platform.name, type(exc).__name__)
            return False


def _failed(platform: Platform, error: str) -> PlatformResult:
    return PlatformResult(platform=platform.name, status=PostStatus.FAILED, error=error)


def _redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "***")
    return text
