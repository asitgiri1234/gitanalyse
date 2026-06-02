import json
import statistics
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.exceptions import AnalysisNotFoundError, InvalidUsernameError
from app.models import ProfileAnalysis
from app.schemas import (
    MostStarredRepository,
    ProfileAnalysisResponse,
    ProfileInsight,
    ProfileListItem,
    RepositoryStats,
    RepositorySummary,
)
from app.services.github import GitHubClient, validate_username


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _days_between(start: datetime, end: datetime | None = None) -> int:
    end = end or datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, (end - start).days)


class ProfileAnalyzerService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.github = GitHubClient()

    def get_by_username(self, username: str) -> ProfileAnalysis | None:
        normalized = username.strip().lstrip("@").lower()
        return (
            self.db.query(ProfileAnalysis)
            .filter(ProfileAnalysis.username == normalized)
            .first()
        )

    def list_all(self) -> list[ProfileListItem]:
        rows = (
            self.db.query(ProfileAnalysis)
            .order_by(ProfileAnalysis.analyzed_at.desc())
            .all()
        )
        return [
            ProfileListItem(
                username=r.username,
                name=r.name,
                followers_count=r.followers_count,
                public_repo_count=r.public_repo_count,
                total_stars_received=r.total_stars_received,
                analyzed_at=r.analyzed_at,
            )
            for r in rows
        ]

    async def analyze(
        self,
        username: str,
        *,
        force_refresh: bool = False,
    ) -> ProfileAnalysisResponse:
        try:
            normalized = validate_username(username).lower()
        except ValueError as exc:
            raise InvalidUsernameError(username, str(exc)) from exc

        existing = self.get_by_username(normalized)
        if existing and not force_refresh:
            return self._to_response(existing, cached=True)

        user = await self.github.fetch_user(normalized)
        repos = await self.github.fetch_repositories(normalized)

        analysis = self._build_analysis(user, repos)
        stored = self._persist(normalized, analysis)
        return self._to_response(stored, cached=False)

    def get_analysis(self, username: str) -> ProfileAnalysisResponse:
        try:
            normalized = validate_username(username).lower()
        except ValueError as exc:
            raise InvalidUsernameError(username, str(exc)) from exc

        row = self.get_by_username(normalized)
        if not row:
            raise AnalysisNotFoundError(normalized)
        return self._to_response(row, cached=True)

    def _build_analysis(
        self, user: dict[str, Any], repos: list[dict[str, Any]]
    ) -> dict[str, Any]:
        joined_at = _parse_dt(user.get("created_at"))
        account_age_days = _days_between(joined_at) if joined_at else None

        repo_summaries = [self._repo_summary(r) for r in repos]
        total_stars = sum(r.stars for r in repo_summaries)
        total_forks = sum(r.forks for r in repo_summaries)

        star_values = [r.stars for r in repo_summaries]
        fork_count = sum(1 for r in repo_summaries if r.is_fork)
        original_count = len(repo_summaries) - fork_count

        language_breakdown: dict[str, int] = {}
        for r in repo_summaries:
            if r.language:
                language_breakdown[r.language] = language_breakdown.get(r.language, 0) + 1

        primary_language = (
            max(language_breakdown, key=language_breakdown.get)
            if language_breakdown
            else None
        )

        now = datetime.now(timezone.utc)
        recent_90d = sum(
            1
            for r in repo_summaries
            if r.pushed_at and _days_between(r.pushed_at, now) <= 90
        )
        recent_365d_created = sum(
            1
            for r in repo_summaries
            if r.created_at and _days_between(r.created_at, now) <= 365
        )

        sorted_by_stars = sorted(repo_summaries, key=lambda r: r.stars, reverse=True)
        most_starred = sorted_by_stars[0] if sorted_by_stars and sorted_by_stars[0].stars > 0 else None

        sorted_by_created = sorted(
            [r for r in repo_summaries if r.created_at],
            key=lambda r: r.created_at,
        )
        repo_stats = RepositoryStats(
            total_repositories=len(repo_summaries),
            original_repositories=original_count,
            forked_repositories=fork_count,
            fork_ratio_percent=round(
                (fork_count / len(repo_summaries) * 100) if repo_summaries else 0.0,
                1,
            ),
            repositories_with_stars=sum(1 for s in star_values if s > 0),
            repositories_without_stars=sum(1 for s in star_values if s == 0),
            average_stars_per_repo=round(
                statistics.mean(star_values) if star_values else 0.0, 2
            ),
            median_stars_per_repo=round(
                statistics.median(star_values) if star_values else 0.0, 2
            ),
            average_forks_per_repo=round(
                statistics.mean([r.forks for r in repo_summaries])
                if repo_summaries
                else 0.0,
                2,
            ),
            languages_used_count=len(language_breakdown),
            primary_language=primary_language,
            recently_updated_count_90d=recent_90d,
            recently_created_count_365d=recent_365d_created,
            oldest_repo_name=sorted_by_created[0].name if sorted_by_created else None,
            newest_repo_name=sorted_by_created[-1].name if sorted_by_created else None,
        )

        most_starred_repo = None
        if most_starred:
            most_starred_repo = MostStarredRepository(
                name=most_starred.name,
                full_name=most_starred.full_name,
                url=most_starred.url,
                stars=most_starred.stars,
                language=most_starred.language,
                description=most_starred.description,
            )

        insights = self._generate_insights(
            user=user,
            followers=user.get("followers", 0),
            following=user.get("following", 0),
            public_repos=user.get("public_repos", 0),
            account_age_days=account_age_days,
            total_stars=total_stars,
            repo_stats=repo_stats,
            language_breakdown=language_breakdown,
            repo_summaries=repo_summaries,
        )

        top_repos = sorted_by_stars[:5]

        return {
            "username": user["login"].lower(),
            "name": user.get("name"),
            "bio": user.get("bio"),
            "avatar_url": user.get("avatar_url"),
            "profile_url": user.get("html_url"),
            "location": user.get("location"),
            "company": user.get("company"),
            "blog": user.get("blog"),
            "followers_count": user.get("followers", 0),
            "following_count": user.get("following", 0),
            "public_repo_count": user.get("public_repos", 0),
            "joined_at": joined_at,
            "account_age_days": account_age_days,
            "total_stars_received": total_stars,
            "total_forks_received": total_forks,
            "total_watchers": sum(
                repo.get("subscribers_count", repo.get("watchers_count", 0)) for repo in repos
            ),
            "most_starred_repo": most_starred_repo,
            "repository_stats": repo_stats,
            "language_breakdown": language_breakdown,
            "top_repositories": top_repos,
            "insights": insights,
        }

    def _repo_summary(self, repo: dict[str, Any]) -> RepositorySummary:
        return RepositorySummary(
            name=repo["name"],
            full_name=repo["full_name"],
            url=repo["html_url"],
            description=repo.get("description"),
            stars=repo.get("stargazers_count", 0),
            forks=repo.get("forks_count", 0),
            language=repo.get("language"),
            is_fork=repo.get("fork", False),
            created_at=_parse_dt(repo.get("created_at")),
            updated_at=_parse_dt(repo.get("updated_at")),
            pushed_at=_parse_dt(repo.get("pushed_at")),
        )

    def _generate_insights(
        self,
        *,
        user: dict[str, Any],
        followers: int,
        following: int,
        public_repos: int,
        account_age_days: int | None,
        total_stars: int,
        repo_stats: RepositoryStats,
        language_breakdown: dict[str, int],
        repo_summaries: list[RepositorySummary],
    ) -> list[ProfileInsight]:
        insights: list[ProfileInsight] = []

        if account_age_days is not None:
            years = round(account_age_days / 365.25, 1)
            insights.append(
                ProfileInsight(
                    category="tenure",
                    title="GitHub tenure",
                    description=(
                        f"Member for {account_age_days} days (~{years} years). "
                        f"Joined on {user.get('created_at', 'unknown')[:10]}."
                    ),
                    severity="info",
                )
            )

        if public_repos == 0:
            insights.append(
                ProfileInsight(
                    category="activity",
                    title="No public repositories",
                    description="This profile has no public repositories to analyze.",
                    severity="neutral",
                )
            )
        else:
            star_rate = (
                repo_stats.repositories_with_stars / repo_stats.total_repositories * 100
            )
            insights.append(
                ProfileInsight(
                    category="impact",
                    title="Repository impact",
                    description=(
                        f"{repo_stats.repositories_with_stars} of {repo_stats.total_repositories} "
                        f"repos ({star_rate:.0f}%) have at least one star. "
                        f"Total stars received: {total_stars:,}."
                    ),
                    severity="positive" if total_stars >= 100 else "info",
                )
            )

        if followers > 0 and following > 0:
            ratio = followers / following
            if ratio >= 5:
                desc = (
                    f"Strong audience signal: {followers:,} followers vs "
                    f"{following:,} following ({ratio:.1f}x)."
                )
                severity = "positive"
            elif ratio < 0.2:
                desc = (
                    f"Follows many more accounts than follow back "
                    f"({following:,} following vs {followers:,} followers)."
                )
                severity = "neutral"
            else:
                desc = (
                    f"Balanced social graph: {followers:,} followers, "
                    f"{following:,} following."
                )
                severity = "info"
            insights.append(
                ProfileInsight(
                    category="community",
                    title="Follower dynamics",
                    description=desc,
                    severity=severity,
                )
            )

        if repo_stats.fork_ratio_percent >= 70 and repo_stats.total_repositories >= 3:
            insights.append(
                ProfileInsight(
                    category="portfolio",
                    title="Fork-heavy portfolio",
                    description=(
                        f"{repo_stats.fork_ratio_percent:.0f}% of public repos are forks. "
                        "Original project work may be limited or kept private."
                    ),
                    severity="neutral",
                )
            )
        elif repo_stats.original_repositories >= 5 and repo_stats.fork_ratio_percent < 30:
            insights.append(
                ProfileInsight(
                    category="portfolio",
                    title="Original builder",
                    description=(
                        f"{repo_stats.original_repositories} original repositories "
                        f"with a low fork ratio ({repo_stats.fork_ratio_percent:.0f}%)."
                    ),
                    severity="positive",
                )
            )

        if repo_stats.primary_language:
            lang_count = repo_stats.languages_used_count
            top_langs = sorted(
                language_breakdown.items(), key=lambda x: x[1], reverse=True
            )[:3]
            lang_str = ", ".join(f"{lang} ({count})" for lang, count in top_langs)
            insights.append(
                ProfileInsight(
                    category="technology",
                    title="Language focus",
                    description=(
                        f"Primary language: {repo_stats.primary_language}. "
                        f"Uses {lang_count} language(s) across repos. Top: {lang_str}."
                    ),
                    severity="info",
                )
            )

        if account_age_days and account_age_days > 365 and public_repos > 0:
            stars_per_year = total_stars / (account_age_days / 365.25)
            repos_per_year = public_repos / (account_age_days / 365.25)
            insights.append(
                ProfileInsight(
                    category="velocity",
                    title="Long-term output pace",
                    description=(
                        f"~{repos_per_year:.1f} public repos/year and "
                        f"~{stars_per_year:.1f} stars received/year on average."
                    ),
                    severity="positive" if stars_per_year >= 50 else "info",
                )
            )

        if repo_stats.recently_updated_count_90d == 0 and repo_stats.total_repositories > 0:
            insights.append(
                ProfileInsight(
                    category="activity",
                    title="Low recent activity",
                    description="No public repository pushes detected in the last 90 days.",
                    severity="caution",
                )
            )
        elif repo_stats.recently_updated_count_90d >= 3:
            insights.append(
                ProfileInsight(
                    category="activity",
                    title="Active maintainer",
                    description=(
                        f"{repo_stats.recently_updated_count_90d} repositories "
                        "updated in the last 90 days."
                    ),
                    severity="positive",
                )
            )

        if total_stars > 0 and repo_stats.median_stars_per_repo < 2:
            top = max(repo_summaries, key=lambda r: r.stars)
            insights.append(
                ProfileInsight(
                    category="impact",
                    title="Concentrated star distribution",
                    description=(
                        f"Most stars are concentrated in '{top.name}' ({top.stars:,} stars). "
                        "Other repositories receive comparatively few stars."
                    ),
                    severity="info",
                )
            )

        if user.get("bio"):
            insights.append(
                ProfileInsight(
                    category="profile",
                    title="Profile completeness",
                    description="Bio is present — profile appears intentionally maintained.",
                    severity="positive",
                )
            )

        return insights

    def _persist(self, username: str, data: dict[str, Any]) -> ProfileAnalysis:
        most = data.get("most_starred_repo")
        repo_stats: RepositoryStats = data["repository_stats"]

        payload = {
            "username": username,
            "name": data.get("name"),
            "bio": data.get("bio"),
            "avatar_url": data.get("avatar_url"),
            "profile_url": data.get("profile_url"),
            "location": data.get("location"),
            "company": data.get("company"),
            "blog": data.get("blog"),
            "followers_count": data["followers_count"],
            "following_count": data["following_count"],
            "public_repo_count": data["public_repo_count"],
            "joined_at": data.get("joined_at"),
            "account_age_days": data.get("account_age_days"),
            "total_stars_received": data["total_stars_received"],
            "total_forks_received": data["total_forks_received"],
            "total_watchers": data["total_watchers"],
            "most_starred_repo_name": most.name if most else None,
            "most_starred_repo_stars": most.stars if most else None,
            "most_starred_repo_url": most.url if most else None,
            "repository_stats_json": repo_stats.model_dump_json(),
            "language_breakdown_json": json.dumps(data["language_breakdown"]),
            "insights_json": json.dumps([i.model_dump() for i in data["insights"]]),
            "top_repositories_json": json.dumps(
                [r.model_dump(mode="json") for r in data["top_repositories"]]
            ),
            "analyzed_at": datetime.now(timezone.utc),
            "source": "github_api",
        }

        existing = self.get_by_username(username)
        if existing:
            for key, value in payload.items():
                setattr(existing, key, value)
            self.db.commit()
            self.db.refresh(existing)
            return existing

        row = ProfileAnalysis(**payload)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _to_response(self, row: ProfileAnalysis, *, cached: bool) -> ProfileAnalysisResponse:
        repo_stats = RepositoryStats.model_validate_json(row.repository_stats_json)
        language_breakdown = json.loads(row.language_breakdown_json)
        insights_raw = json.loads(row.insights_json)
        top_repos_raw = json.loads(row.top_repositories_json)

        most_starred = None
        if row.most_starred_repo_name and row.most_starred_repo_stars is not None:
            top_match = next(
                (
                    r
                    for r in top_repos_raw
                    if r.get("name") == row.most_starred_repo_name
                ),
                None,
            )
            most_starred = MostStarredRepository(
                name=row.most_starred_repo_name,
                full_name=top_match["full_name"] if top_match else row.most_starred_repo_name,
                url=row.most_starred_repo_url or (top_match or {}).get("url", ""),
                stars=row.most_starred_repo_stars,
                language=(top_match or {}).get("language"),
                description=(top_match or {}).get("description"),
            )

        account_age_years = None
        if row.account_age_days is not None:
            account_age_years = round(row.account_age_days / 365.25, 2)

        return ProfileAnalysisResponse(
            username=row.username,
            name=row.name,
            bio=row.bio,
            avatar_url=row.avatar_url,
            profile_url=row.profile_url,
            location=row.location,
            company=row.company,
            blog=row.blog,
            followers_count=row.followers_count,
            following_count=row.following_count,
            public_repo_count=row.public_repo_count,
            joined_at=row.joined_at,
            account_age_days=row.account_age_days,
            account_age_years=account_age_years,
            total_stars_received=row.total_stars_received,
            total_forks_received=row.total_forks_received,
            total_watchers=row.total_watchers,
            most_starred_repository=most_starred,
            repository_stats=repo_stats,
            language_breakdown=language_breakdown,
            top_repositories=[RepositorySummary.model_validate(r) for r in top_repos_raw],
            insights=[ProfileInsight.model_validate(i) for i in insights_raw],
            analyzed_at=row.analyzed_at,
            cached=cached,
        )
