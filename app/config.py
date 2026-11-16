"""Application configuration.

All credentials are read from environment variables (or a local ``.env`` file,
which is git-ignored). Nothing secret is ever hard-coded.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General -----------------------------------------------------------
    app_name: str = "Automated Multi-Platform Posting System"
    log_level: str = "INFO"
    http_timeout: float = Field(15.0, description="Per-HTTP-request timeout (s)")
    platform_timeout: float = Field(30.0, description="Total budget per platform (s)")
    max_retries: int = Field(2, ge=0, le=5)
    verify_public_access: bool = True
    user_agent: str = "automated-posting/1.0 (+https://github.com)"

    # --- Telegraph (telegra.ph) -------------------------------------------
    telegraph_enabled: bool = True
    telegraph_access_token: str | None = None
    telegraph_short_name: str = "autoposter"
    telegraph_author_name: str = "Automated Posting"

    # --- Mastodon ----------------------------------------------------------
    mastodon_base_url: str = "https://mastodon.social"
    mastodon_access_token: str | None = None

    # --- Bluesky (AT Protocol) --------------------------------------------
    bluesky_service: str = "https://bsky.social"
    bluesky_handle: str | None = None
    bluesky_app_password: str | None = None

    # --- Telegram Bot API --------------------------------------------------
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None  # e.g. "@my_public_channel"

    # --- Discord -----------------------------------------------------------
    discord_webhook_url: str | None = None

    # --- GitHub Gists ------------------------------------------------------
    github_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
