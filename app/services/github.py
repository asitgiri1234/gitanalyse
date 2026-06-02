import re
from typing import Any

import httpx

from app.config import settings
from app.exceptions import GitHubAPIError, ProfileNotFoundError, RateLimitError

GITHUB_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$")


def validate_username(username: str) -> str:
    cleaned = username.strip().lstrip("@")
    if not cleaned:
        raise ValueError("Username cannot be empty.")
    if len(cleaned) > 39:
        raise ValueError("Username cannot exceed 39 characters.")
    if not GITHUB_USERNAME_PATTERN.match(cleaned):
        raise ValueError(
            "Username may only contain alphanumeric characters or single hyphens "
            "not at the start or end."
        )
    return cleaned


class GitHubClient:
    def __init__(self) -> None:
        headers = {
            "Accept": "application/vnd.github+json, application/vnd.github.mercy-preview+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "gitanalyse/1.0",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        self._headers = headers
        self._base = settings.github_api_base.rstrip("/")
        self._timeout = settings.request_timeout

    async def _request(self, path: str) -> Any:
        url = f"{self._base}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise GitHubAPIError("GitHub API request timed out.") from exc
        except httpx.RequestError as exc:
            raise GitHubAPIError(f"Failed to reach GitHub API: {exc}") from exc

        if response.status_code == 404:
            return None
        if response.status_code == 403:
            remaining = response.headers.get("X-RateLimit-Remaining")
            if remaining == "0":
                raise RateLimitError(reset_at=response.headers.get("X-RateLimit-Reset"))
        if response.status_code >= 400:
            raise GitHubAPIError(
                f"GitHub API returned status {response.status_code}.",
                extra={"status_code": response.status_code, "body": response.text[:500]},
            )

        return response.json()

    async def fetch_user(self, username: str) -> dict[str, Any]:
        data = await self._request(f"/users/{username}")
        if data is None:
            raise ProfileNotFoundError(username)
        return data

    async def fetch_repositories(self, username: str) -> list[dict[str, Any]]:
        repos: list[dict[str, Any]] = []
        page = 1
        per_page = 100

        while True:
            batch = await self._request(
                f"/users/{username}/repos?per_page={per_page}&page={page}&sort=updated"
            )
            if batch is None:
                break
            if not isinstance(batch, list) or not batch:
                break
            repos.extend(batch)
            if len(batch) < per_page:
                break
            page += 1

        return repos
