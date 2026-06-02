from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RepositorySummary(BaseModel):
    name: str
    full_name: str
    url: str
    description: str | None = None
    stars: int
    forks: int
    language: str | None = None
    is_fork: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    pushed_at: datetime | None = None


class RepositoryStats(BaseModel):
    total_repositories: int
    original_repositories: int
    forked_repositories: int
    fork_ratio_percent: float
    repositories_with_stars: int
    repositories_without_stars: int
    average_stars_per_repo: float
    median_stars_per_repo: float
    average_forks_per_repo: float
    languages_used_count: int
    primary_language: str | None = None
    recently_updated_count_90d: int
    recently_created_count_365d: int
    oldest_repo_name: str | None = None
    newest_repo_name: str | None = None


class MostStarredRepository(BaseModel):
    name: str
    full_name: str
    url: str
    stars: int
    language: str | None = None
    description: str | None = None


class ProfileInsight(BaseModel):
    category: str
    title: str
    description: str
    severity: str = Field(
        description="info | positive | neutral | caution",
        default="info",
    )


class ProfileAnalysisResponse(BaseModel):
    username: str
    name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    profile_url: str | None = None
    location: str | None = None
    company: str | None = None
    blog: str | None = None

    followers_count: int
    following_count: int
    public_repo_count: int

    joined_at: datetime | None = None
    account_age_days: int | None = None
    account_age_years: float | None = None

    total_stars_received: int
    total_forks_received: int
    total_watchers: int

    most_starred_repository: MostStarredRepository | None = None
    repository_stats: RepositoryStats
    language_breakdown: dict[str, int]
    top_repositories: list[RepositorySummary]
    insights: list[ProfileInsight]

    analyzed_at: datetime
    cached: bool = Field(
        description="True when returned from database without a new GitHub API call"
    )

    model_config = {"from_attributes": True}


class ProfileListItem(BaseModel):
    username: str
    name: str | None = None
    followers_count: int
    public_repo_count: int
    total_stars_received: int
    analyzed_at: datetime


class ProfileListResponse(BaseModel):
    total: int
    profiles: list[ProfileListItem]


class AnalyzeRequest(BaseModel):
    username: str = Field(
        min_length=1,
        max_length=39,
        description="GitHub username (1-39 characters)",
    )
    force_refresh: bool = Field(
        default=False,
        description="Re-fetch from GitHub even if a cached analysis exists",
    )


class ErrorResponse(BaseModel):
    detail: str
    error_code: str | None = None
    extra: dict[str, Any] | None = None
