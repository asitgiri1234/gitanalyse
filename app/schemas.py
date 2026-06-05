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
    topics: list[str] = Field(default_factory=list)
    has_description: bool = False
    has_license: bool = False
    has_homepage: bool = False
    has_wiki: bool = False
    open_issues_count: int = 0
    quality_score: float = 0.0


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
    repositories_with_license_percent: float = 0.0
    repositories_with_description_percent: float = 0.0
    repositories_with_homepage_percent: float = 0.0
    repositories_with_wiki_percent: float = 0.0
    repositories_with_topics_percent: float = 0.0
    archived_repositories_count: int = 0
    disabled_repositories_count: int = 0
    stale_repositories_180d_count: int = 0
    average_open_issues_per_repo: float = 0.0
    primary_domain: str | None = None
    domain_confidence_percent: float = 0.0
    domain_breakdown: dict[str, float] = Field(default_factory=dict)


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


class UserSuggestion(BaseModel):
    username: str
    name: str | None = None
    avatar_url: str | None = None
    profile_url: str | None = None
    source: str = Field(
        description="cache | github",
        default="github",
    )


class UserSuggestionResponse(BaseModel):
    query: str
    total: int
    suggestions: list[UserSuggestion]


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
