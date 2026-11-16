# Automated Multi-Platform Posting System

A FastAPI service that takes one short message with exactly one CTA link and posts it to **6 third-party platforms** at the same time, through their official APIs. Each platform is handled on its own, so one platform failing never stops the others.

| # | Platform | API | Auth | Public URL |
|---|----------|-----|------|------------|
| 1 | **Telegraph** (telegra.ph) | [`createAccount` / `createPage`](https://telegra.ph/api) | Access token (auto-created if absent) | ✅ `https://telegra.ph/<path>` |
| 2 | **Mastodon** | [`POST /api/v1/statuses`](https://docs.joinmastodon.org/methods/statuses/#create) | OAuth bearer token (`write:statuses`) | ✅ `https://<instance>/@user/<id>` |
| 3 | **Bluesky** (AT Protocol) | [`createSession` + `repo.createRecord`](https://docs.bsky.app/docs/advanced-guides/posts) | Handle + app password → JWT | ✅ `https://bsky.app/profile/<handle>/post/<rkey>` |
| 4 | **Telegram** | [Bot API `sendMessage`](https://core.telegram.org/bots/api#sendmessage) | Bot token | ✅ `https://t.me/<channel>/<id>` (public channels) |
| 5 | **Discord** | [Execute Webhook](https://discord.com/developers/docs/resources/webhook#execute-webhook) | Webhook URL | ❌ jump link (members only) |
| 6 | **GitHub Gist** | [`POST /gists`](https://docs.github.com/en/rest/gists/gists#create-a-gist) | Fine-grained PAT (Gists: write) | ✅ `https://gist.github.com/<user>/<id>` |

Telegraph needs no sign-up, so **the project posts to at least one platform with zero configuration**.

---

## Quick start

```bash
git clone <this-repo> && cd automated-posting
python3 -m venv .venv && source .venv/bin/activate     # Python 3.10+
pip install -r requirements-dev.txt
cp .env.example .env                                    # fill in the credentials you have
uvicorn app.main:app --host 0.0.0.0 --port 4000
```

- Swagger UI: <http://localhost:4000/docs>
- Health and which platforms are configured: <http://localhost:4000/health>
- Tests: `pytest` (52 tests, all HTTP mocked, no network or credentials needed)

## API

### `POST /posting`

```bash
curl -X POST http://localhost:4000/posting \
  -H "Content-Type: application/json" \
  -d '{"message": "Check out our latest business platform and grow your online visibility. https://example.com"}'
```

**200 OK.** Every platform appears in `results`, whether it succeeded or failed:

```json
{
  "success": true,
  "summary": { "total": 6, "succeeded": 2, "failed": 4 },
  "results": [
    {
      "platform": "Telegraph",
      "status": "success",
      "posted_url": "https://telegra.ph/Check-out-our-latest-business-platform-11-16",
      "public_access": true,
      "date": "2026-11-16",
      "time": "10:30:00",
      "error": null
    },
    {
      "platform": "Mastodon",
      "status": "failed",
      "posted_url": null,
      "public_access": false,
      "date": null,
      "time": null,
      "error": "HTTP 401: The access token is invalid"
    },
    {
      "platform": "Bluesky",
      "status": "failed",
      "posted_url": null,
      "public_access": false,
      "date": null,
      "time": null,
      "error": "Platform not configured. Set: BLUESKY_HANDLE, BLUESKY_APP_PASSWORD"
    }
  ]
}
```

> The response above is an illustrative sample. Real captured output is in [`docs/`](docs/).

| Field | Meaning |
|---|---|
| `platform` | Platform name |
| `status` | `success` / `failed` |
| `posted_url` | URL of the published content |
| `public_access` | **Checked, not assumed**: the URL is fetched anonymously after posting (Bluesky uses its public AppView API instead, see below) |
| `date` / `time` | Posting timestamp, taken from the platform's response when available, always **UTC** |
| `error` | Readable reason for a failure, with secrets removed |

`success` is `true` when at least one platform succeeded, and `summary` gives the counts.

### Validation (`422 Unprocessable Content`)

```json
{
  "success": false,
  "error": "Validation failed",
  "details": [
    { "field": "message", "message": "Message must include exactly one CTA link; found 2: https://a.com, https://b.com." }
  ]
}
```

Rules (in `app/validation.py`, written as plain functions so they're easy to test):

- The message is trimmed, must not be empty, and must be **≤ 200 characters**
- It must contain **exactly one** link. `www.example.com` without a scheme still counts toward the total, so "two links" is detected.
- The link must use `http`/`https` and contain no `user:pass@` credentials. Its port must be valid. Its host must be a real public domain (valid labels and TLD, IDN allowed) or a **public** IP. `localhost`, single-label hosts and private or loopback IPs are rejected.
- Trailing punctuation like `.`, `)` or `!` is not treated as part of the link
- Missing fields, wrong types and malformed JSON all return the same error format

## Architecture

```text
app/
├── main.py                 FastAPI app, lifespan (shared httpx client), routes, 422 handler
├── config.py               pydantic-settings: env vars / .env
├── schemas.py              Request/response models (drive the OpenAPI docs)
├── validation.py           Message and URL rules
├── platforms/
│   ├── base.py             Platform base class, retry policy, error extraction
│   ├── __init__.py         Registry: the platform list is chosen here, not by the client
│   ├── telegraph.py  mastodon.py  bluesky.py
│   └── telegram.py   discord.py   github_gist.py
└── services/
    └── posting_service.py  Concurrent fan-out with per-platform isolation
tests/                      test_validation.py, test_platforms.py, test_posting.py
```

### Design decisions

- **Concurrent and isolated.** `asyncio.gather` runs every platform at the same time, so total time is roughly the slowest platform, not the sum. Each platform runs inside `_post_one`, which never raises. It turns `PlatformError`, timeouts (a `PLATFORM_TIMEOUT` limit per platform) and even unexpected bugs into a `failed` result. One broken integration can't take down the request.
- **Safe retries, no duplicate posts.** A `POST` that creates content is not idempotent. The app retries only when it knows the platform did *not* process the request: connection errors, `429` and `503` (it honours `Retry-After`, capped). A *read* timeout is never retried, because the post may already exist. Mastodon also gets an `Idempotency-Key` header.
- **Public access is checked.** After a successful post, the app fetches the URL anonymously. Bluesky's web app returns 200 for any path, so it asks the public AppView (`app.bsky.feed.getPosts`) instead. Discord messages always need a login, so it reports `false`. A failed check never turns a successful post into a failure.
- **Bluesky link facets.** Bluesky doesn't detect links automatically. The CTA is declared as a `richtext.facet#link` using UTF-8 *byte* offsets, and a test covers emoji.
- **Security:**
  - Credentials come only from env vars, and `.env` is git-ignored
  - Error messages are scrubbed of configured secrets
  - `httpx` logging is set to WARNING, because Telegram and Discord put secrets in the URL
  - Discord `allowed_mentions` is empty, so user text can't ping `@everyone`
- **Extensible.** To add a platform, subclass `Platform` and implement `missing_config()` and `publish()`. Optionally override `is_publicly_accessible()`. Then add the class to `PLATFORM_CLASSES`.
- **Unconfigured platforms** are reported as `failed` with the exact env vars to set, rather than silently left out, so the response always covers every platform.
- **Testable.** Platforms receive an injected `httpx.AsyncClient`, and the tests swap in `httpx.MockTransport`. The endpoint tests override `get_posting_service`.

## Getting credentials

| Platform | Steps |
|---|---|
| Telegraph | Nothing to do. Optionally save the auto-created token to `TELEGRAPH_ACCESS_TOKEN` so every page belongs to one account. |
| Mastodon | Go to Preferences → Development → New application with scope `write:statuses`, then copy the access token. Set `MASTODON_BASE_URL` to your instance. |
| Bluesky | Go to Settings → Privacy and security → App passwords. Use your handle and the app password, never your main password. |
| Telegram | Create a bot with [@BotFather](https://t.me/BotFather). Create a **public** channel and add the bot as an admin. Set `TELEGRAM_CHAT_ID=@channelname`. |
| Discord | Go to Server Settings → Integrations → Webhooks → New Webhook and copy the URL. |
| GitHub Gist | Go to Settings → Developer settings → Fine-grained tokens. Set Account permissions → Gists to Read and write. |

## Evidence

- [`docs/sample-session.txt`](docs/sample-session.txt): curl session against the running server (health, posting, validation errors)
- [`docs/sample-server.log`](docs/sample-server.log): matching server log

## Notes and limitations

- The spec mentions "LLM platforms". The major LLM providers (OpenAI, Anthropic, Gemini) offer no API for *publishing* public content, so this project integrates content platforms. Adding a provider later is just another `Platform` subclass.
- Platform rate limits and anti-spam rules apply. Don't run this in a loop with promotional content.
- Bare domains without a scheme or `www.` (for example `example.com`) are not detected as links. Doing so causes false positives like `Node.js`.
