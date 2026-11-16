"""Each integration exercised against a mocked HTTP transport — no network."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.platforms.base import PlatformError
from app.platforms.bluesky import BlueskyPlatform, link_facet
from app.platforms.discord import DiscordPlatform
from app.platforms.github_gist import GitHubGistPlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.telegram import TelegramPlatform
from app.platforms.telegraph import TelegraphPlatform, build_content
from tests.conftest import body_json, mock_client, run

MSG = "Grow your visibility 🚀 https://example.com today"
URL = "https://example.com"


# --------------------------------------------------------------- Telegraph
def test_telegraph_creates_account_then_page(settings):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        form = parse_qs(request.content.decode())
        if request.url.path == "/createAccount":
            return httpx.Response(200, json={"ok": True, "result": {"access_token": "tg-token"}})
        assert form["access_token"] == ["tg-token"]
        assert json.loads(form["content"][0]) == build_content(MSG, URL)
        return httpx.Response(200, json={"ok": True, "result": {"url": "https://telegra.ph/Grow-11-16", "path": "Grow-11-16"}})

    platform = TelegraphPlatform(settings, mock_client(handler))
    outcome = run(platform.publish(MSG, URL))
    run(platform.publish(MSG, URL))  # token is cached: no second createAccount

    assert outcome.url == "https://telegra.ph/Grow-11-16"
    assert calls == ["/createAccount", "/createPage", "/createPage"]


def test_telegraph_content_renders_link_node():
    assert build_content(MSG, URL) == [
        {"tag": "p", "children": [
            "Grow your visibility 🚀 ",
            {"tag": "a", "attrs": {"href": URL}, "children": [URL]},
            " today",
        ]}
    ]


def test_telegraph_api_error(settings):
    handler = lambda r: httpx.Response(200, json={"ok": False, "error": "ACCESS_TOKEN_INVALID"})
    with pytest.raises(PlatformError, match="ACCESS_TOKEN_INVALID"):
        run(TelegraphPlatform(settings, mock_client(handler)).publish(MSG, URL))


# ---------------------------------------------------------------- Mastodon
def test_mastodon_posts_public_status_with_idempotency_key(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://mastodon.social/api/v1/statuses"
        assert request.headers["Authorization"] == "Bearer mastodon-secret-token"
        assert request.headers["Idempotency-Key"]
        assert parse_qs(request.content.decode()) == {"status": [MSG], "visibility": ["public"]}
        return httpx.Response(200, json={
            "id": "1", "url": "https://mastodon.social/@me/1",
            "created_at": "2026-11-16T10:30:00.000Z",
        })

    outcome = run(MastodonPlatform(settings, mock_client(handler)).publish(MSG, URL))
    assert outcome.url == "https://mastodon.social/@me/1"
    assert outcome.posted_at.isoformat() == "2026-11-16T10:30:00+00:00"


def test_mastodon_auth_error_is_reported(settings):
    handler = lambda r: httpx.Response(401, json={"error": "The access token is invalid"})
    with pytest.raises(PlatformError, match="HTTP 401: The access token is invalid"):
        run(MastodonPlatform(settings, mock_client(handler)).publish(MSG, URL))


# ----------------------------------------------------------------- Bluesky
def test_bluesky_link_facet_uses_utf8_byte_offsets():
    facet = link_facet(MSG, URL)
    start = len("Grow your visibility 🚀 ".encode())  # emoji = 4 bytes
    assert facet["index"] == {"byteStart": start, "byteEnd": start + len(URL)}
    assert MSG.encode()[start:start + len(URL)].decode() == URL


def test_bluesky_session_then_record(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("createSession"):
            assert body_json(request) == {"identifier": "tester.bsky.social", "password": "abcd-efgh-ijkl-mnop"}
            return httpx.Response(200, json={"accessJwt": "jwt", "did": "did:plc:abc", "handle": "tester.bsky.social"})
        assert request.headers["Authorization"] == "Bearer jwt"
        payload = body_json(request)
        assert payload["repo"] == "did:plc:abc"
        assert payload["record"]["text"] == MSG
        assert payload["record"]["facets"][0]["features"][0]["uri"] == URL
        return httpx.Response(200, json={"uri": "at://did:plc:abc/app.bsky.feed.post/3kxyz", "cid": "c"})

    outcome = run(BlueskyPlatform(settings, mock_client(handler)).publish(MSG, URL))
    assert outcome.url == "https://bsky.app/profile/tester.bsky.social/post/3kxyz"


def test_bluesky_public_check_uses_appview(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "public.api.bsky.app"
        return httpx.Response(200, json={"posts": [{"uri": "at://x"}]})

    platform = BlueskyPlatform(settings, mock_client(handler))
    from app.platforms.base import PostOutcome
    assert run(platform.is_publicly_accessible(PostOutcome(url="u", extra={"uri": "at://x"}))) is True


# ---------------------------------------------------------------- Telegram
def test_telegram_public_channel_url(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/bot123456:TELEGRAM-SECRET/sendMessage"
        assert body_json(request)["chat_id"] == "@my_channel"
        return httpx.Response(200, json={"ok": True, "result": {
            "message_id": 42, "date": 1795343400, "chat": {"id": -1001234, "username": "my_channel"},
        }})

    outcome = run(TelegramPlatform(settings, mock_client(handler)).publish(MSG, URL))
    assert outcome.url == "https://t.me/my_channel/42"


def test_telegram_private_channel_url(settings):
    handler = lambda r: httpx.Response(200, json={"ok": True, "result": {
        "message_id": 7, "date": 1795343400, "chat": {"id": -1009876},
    }})
    outcome = run(TelegramPlatform(settings, mock_client(handler)).publish(MSG, URL))
    assert outcome.url == "https://t.me/c/9876/7"


def test_telegram_error_description(settings):
    handler = lambda r: httpx.Response(400, json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})
    with pytest.raises(PlatformError, match="chat not found"):
        run(TelegramPlatform(settings, mock_client(handler)).publish(MSG, URL))


# ----------------------------------------------------------------- Discord
def test_discord_webhook_disables_mentions_and_builds_jump_url(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":  # webhook info lookup for guild_id
            return httpx.Response(200, json={"guild_id": "999", "channel_id": "222"})
        assert request.url.params["wait"] == "true"
        assert body_json(request)["allowed_mentions"] == {"parse": []}
        return httpx.Response(200, json={"id": "333", "channel_id": "222", "timestamp": "2026-11-16T10:30:00+00:00"})

    platform = DiscordPlatform(settings, mock_client(handler))
    outcome = run(platform.publish(MSG, URL))
    assert outcome.url == "https://discord.com/channels/999/222/333"
    assert run(platform.is_publicly_accessible(outcome)) is False


# ------------------------------------------------------------- GitHub Gist
def test_gist_created_public_with_markdown_link(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = body_json(request)
        assert request.headers["Authorization"] == "Bearer ghp_github_secret_token"
        assert payload["public"] is True
        assert f"[{URL}]({URL})" in payload["files"]["message.md"]["content"]
        return httpx.Response(201, json={"id": "g1", "html_url": "https://gist.github.com/me/g1", "created_at": "2026-11-16T10:30:00Z"})

    outcome = run(GitHubGistPlatform(settings, mock_client(handler)).publish(MSG, URL))
    assert outcome.url == "https://gist.github.com/me/g1"


# ------------------------------------------------------------ retry policy
def test_retries_on_429_then_succeeds(settings, monkeypatch):
    responses = iter([
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(201, json={"id": "g1", "html_url": "https://gist.github.com/me/g1", "created_at": "2026-11-16T10:30:00Z"}),
    ])
    outcome = run(GitHubGistPlatform(settings, mock_client(lambda r: next(responses))).publish(MSG, URL))
    assert outcome.url.endswith("g1")


def test_read_timeout_is_not_retried(settings):
    """A read timeout means the post may exist; retrying could duplicate it."""
    attempts = []

    def handler(request):
        attempts.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(PlatformError, match="Timed out"):
        run(GitHubGistPlatform(settings, mock_client(handler)).publish(MSG, URL))
    assert len(attempts) == 1


def test_connect_error_is_retried(settings):
    attempts = []

    def handler(request):
        attempts.append(1)
        raise httpx.ConnectError("dns", request=request)

    with pytest.raises(PlatformError, match="Network error"):
        run(GitHubGistPlatform(settings, mock_client(handler)).publish(MSG, URL))
    assert len(attempts) == settings.max_retries + 1
