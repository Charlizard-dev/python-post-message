"""GitHub Gists — https://docs.github.com/en/rest/gists/gists#create-a-gist

Creates a public Markdown gist. Needs a fine-grained token with
"Gists: read & write" (or a classic token with the ``gist`` scope).
"""

from __future__ import annotations

from datetime import datetime

from app.platforms.base import Platform, PostOutcome, split_on_link, title_from_message


class GitHubGistPlatform(Platform):
    name = "GitHub Gist"
    docs_url = "https://docs.github.com/en/rest/gists/gists#create-a-gist"

    def missing_config(self) -> list[str]:
        return [] if self.settings.github_token else ["GITHUB_TOKEN"]

    def secrets(self) -> list[str]:
        return [self.settings.github_token or ""]

    async def publish(self, message: str, cta_url: str) -> PostOutcome:
        before, after = split_on_link(message, cta_url)
        markdown = f"{before}[{cta_url}]({cta_url}){after}\n"
        response = await self._request(
            "POST",
            "https://api.github.com/gists",
            headers={
                "Authorization": f"Bearer {self.settings.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "description": title_from_message(message, cta_url),
                "public": True,
                "files": {"message.md": {"content": markdown}},
            },
        )
        gist = response.json()
        return PostOutcome(
            url=gist["html_url"],
            posted_at=datetime.fromisoformat(gist["created_at"].replace("Z", "+00:00")),
            extra={"id": gist["id"]},
        )
