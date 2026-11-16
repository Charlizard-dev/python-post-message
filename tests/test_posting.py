"""Service orchestration + HTTP endpoint tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_posting_service
from app.platforms.base import Platform, PlatformError, PostOutcome
from app.services.posting_service import PostingService
from tests.conftest import run

VALID = "Check out our latest business platform and grow your online visibility. https://example.com"


class FakePlatform(Platform):
    def __init__(self, name, settings, behaviour="ok", configured=True, public=True, secret=""):
        super().__init__(settings, client=None)
        self.name = name
        self.behaviour = behaviour
        self.configured = configured
        self.public = public
        self.secret = secret
        self.calls = 0

    def missing_config(self):
        return [] if self.configured else [f"{self.name.upper()}_TOKEN"]

    def secrets(self):
        return [self.secret]

    async def publish(self, message, cta_url):
        self.calls += 1
        if self.behaviour == "platform_error":
            raise PlatformError(f"HTTP 401: bad token {self.secret}")
        if self.behaviour == "crash":
            raise KeyError("unexpected")
        if self.behaviour == "hang":
            await asyncio.sleep(10)
        return PostOutcome(
            url=f"https://{self.name.lower()}.example/post/1",
            posted_at=datetime(2026, 11, 16, 10, 30, 0, tzinfo=timezone.utc),
        )

    async def is_publicly_accessible(self, outcome):
        if self.public == "boom":
            raise RuntimeError("check failed")
        return self.public


# ------------------------------------------------------------------ service
def test_one_failure_does_not_stop_other_platforms(settings):
    settings.platform_timeout = 0.2
    platforms = [
        FakePlatform("A", settings),
        FakePlatform("B", settings, behaviour="platform_error", secret="supersecret123"),
        FakePlatform("C", settings, behaviour="crash"),
        FakePlatform("D", settings, behaviour="hang"),
        FakePlatform("E", settings, configured=False),
        FakePlatform("F", settings, public="boom"),
    ]
    results = run(PostingService(platforms, settings).post_everywhere(VALID, "https://example.com"))
    by_name = {r.platform: r for r in results}

    assert [r.platform for r in results] == ["A", "B", "C", "D", "E", "F"]  # order preserved

    a = by_name["A"]
    assert (a.status.value, a.posted_url, a.public_access, a.date, a.time, a.error) == (
        "success", "https://a.example/post/1", True, "2026-11-16", "10:30:00", None)

    assert by_name["B"].status.value == "failed"
    assert by_name["B"].error == "HTTP 401: bad token ***"  # secret redacted
    assert by_name["C"].error == "Unexpected error: KeyError"
    assert by_name["D"].error.startswith("Timed out")
    assert by_name["E"].error == "Platform not configured. Set: E_TOKEN"
    assert platforms[4].calls == 0
    # A failing public-access check never turns a success into a failure.
    assert by_name["F"].status.value == "success" and by_name["F"].public_access is False

    for failed in (by_name[n] for n in "BCDE"):
        assert (failed.posted_url, failed.public_access, failed.date, failed.time) == (None, False, None, None)


def test_platforms_run_concurrently(settings):
    class Slow(FakePlatform):
        async def publish(self, message, cta_url):
            await asyncio.sleep(0.3)
            return PostOutcome(url=None)

    platforms = [Slow(str(i), settings) for i in range(5)]
    loop_start = asyncio.run(_timed(PostingService(platforms, settings), VALID))
    assert loop_start < 1.0  # 5 x 0.3s sequential would be 1.5s


async def _timed(service, message):
    start = asyncio.get_running_loop().time()
    await service.post_everywhere(message, "https://example.com")
    return asyncio.get_running_loop().time() - start


# ----------------------------------------------------------------- endpoint
@pytest.fixture
def client(settings):
    platforms = [
        FakePlatform("Alpha", settings),
        FakePlatform("Beta", settings, behaviour="platform_error"),
    ]
    app.dependency_overrides[get_posting_service] = lambda: PostingService(platforms, settings)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_post_returns_per_platform_results(client):
    response = client.post("/posting", json={"message": VALID})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["summary"] == {"total": 2, "succeeded": 1, "failed": 1}
    assert set(body["results"][0]) == {
        "platform", "status", "posted_url", "public_access", "date", "time", "error"}
    assert body["results"][1]["status"] == "failed"


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ({"message": "x" * 201}, "must not exceed 200"),
        ({"message": "no link"}, "none was found"),
        ({"message": "https://a.com https://b.com"}, "found 2"),
        ({"message": "see https://localhost"}, "public domain"),
        ({}, "Field required"),
        ({"message": 123}, "valid string"),
    ],
)
def test_validation_errors(client, payload, fragment):
    response = client.post("/posting", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["details"][0]["field"] == "message"
    assert fragment in body["details"][0]["message"]


def test_malformed_json(client):
    response = client.post("/posting", content="{not json", headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json()["success"] is False


def test_all_failed_reports_success_false(settings):
    platforms = [FakePlatform("X", settings, behaviour="platform_error")]
    app.dependency_overrides[get_posting_service] = lambda: PostingService(platforms, settings)
    try:
        with TestClient(app) as c:
            body = c.post("/posting", json={"message": VALID}).json()
    finally:
        app.dependency_overrides.clear()
    assert body["success"] is False
    assert body["summary"]["failed"] == 1


def test_openapi_docs_available(client):
    assert client.get("/docs").status_code == 200
    assert "/posting" in client.get("/openapi.json").json()["paths"]
