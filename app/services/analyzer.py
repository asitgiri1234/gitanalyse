import json
import statistics
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_
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
    UserSuggestion,
)
from app.services.github import GitHubClient, validate_username

DOMAIN_KEYWORDS: dict[str, set[str]] = {
    "web_development": {
        "react",
        "vue",
        "angular",
        "next",
        "frontend",
        "tailwind",
        "html",
        "css",
        "web",
    },
    "backend_api": {
        "api",
        "backend",
        "server",
        "fastapi",
        "django",
        "flask",
        "spring",
        "node",
        "express",
        "microservice",
    },
    "data_ai": {
        "ml",
        "ai",
        "llm",
        "tensorflow",
        "pytorch",
        "data",
        "pandas",
        "numpy",
        "computer-vision",
        "nlp",
    },
    "devops_cloud": {
        "docker",
        "kubernetes",
        "terraform",
        "aws",
        "gcp",
        "azure",
        "devops",
        "ci",
        "cd",
        "helm",
    },
    "mobile": {
        "android",
        "ios",
        "flutter",
        "react-native",
        "swift",
        "kotlin",
        "mobile",
    },
    "security": {
        "security",
        "cryptography",
        "pentest",
        "vulnerability",
        "auth",
        "jwt",
        "encryption",
    },
}

LANGUAGE_DOMAIN_HINTS: dict[str, str] = {
    "typescript": "web_development",
    "javascript": "web_development",
    "html": "web_development",
    "css": "web_development",
    "python": "data_ai",
    "jupyter notebook": "data_ai",
    "go": "backend_api",
    "java": "backend_api",
    "c#": "backend_api",
    "rust": "backend_api",
    "kotlin": "mobile",
    "swift": "mobile",
    "hcl": "devops_cloud",
    "dockerfile": "devops_cloud",
}


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

    def _search_cached_suggestions(self, query: str, limit: int) -> list[UserSuggestion]:
        pattern = f"%{query.lower()}%"
        rows = (
            self.db.query(ProfileAnalysis)
            .filter(
                or_(
                    func.lower(ProfileAnalysis.username).like(pattern),
                    func.lower(ProfileAnalysis.name).like(pattern),
                )
            )
            .order_by(ProfileAnalysis.analyzed_at.desc())
            .limit(limit)
            .all()
        )
        return [
            UserSuggestion(
                username=r.username,
                name=r.name,
                avatar_url=r.avatar_url,
                profile_url=r.profile_url,
                source="cache",
            )
            for r in rows
        ]

    async def search_suggestions(self, query: str, limit: int = 8) -> list[UserSuggestion]:
        cleaned = query.strip().lstrip("@")
        if len(cleaned) < 2:
            return []

        capped = max(1, min(limit, 20))
        suggestions = self._search_cached_suggestions(cleaned, capped)
        seen = {s.username.lower() for s in suggestions}

        remaining = capped - len(suggestions)
        if remaining > 0:
            try:
                github_items = await self.github.search_users(cleaned, per_page=remaining)
            except Exception:
                github_items = []

            for item in github_items:
                login = item.get("login")
                if not isinstance(login, str) or not login:
                    continue
                normalized = login.lower()
                if normalized in seen:
                    continue
                seen.add(normalized)
                suggestions.append(
                    UserSuggestion(
                        username=login,
                        name=None,
                        avatar_url=item.get("avatar_url"),
                        profile_url=item.get("html_url"),
                        source="github",
                    )
                )
                if len(suggestions) >= capped:
                    break

        return suggestions

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
        quality_summary = self._build_repo_quality_summary(repo_summaries, repos, now)
        domain_analysis = self._build_domain_analysis(
            repo_summaries=repo_summaries,
            repos=repos,
            language_breakdown=language_breakdown,
        )

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
            repositories_with_license_percent=quality_summary["repositories_with_license_percent"],
            repositories_with_description_percent=quality_summary["repositories_with_description_percent"],
            repositories_with_homepage_percent=quality_summary["repositories_with_homepage_percent"],
            repositories_with_wiki_percent=quality_summary["repositories_with_wiki_percent"],
            repositories_with_topics_percent=quality_summary["repositories_with_topics_percent"],
            archived_repositories_count=quality_summary["archived_repositories_count"],
            disabled_repositories_count=quality_summary["disabled_repositories_count"],
            stale_repositories_180d_count=quality_summary["stale_repositories_180d_count"],
            average_open_issues_per_repo=quality_summary["average_open_issues_per_repo"],
            primary_domain=domain_analysis["primary_domain"],
            domain_confidence_percent=domain_analysis["domain_confidence_percent"],
            domain_breakdown=domain_analysis["domain_breakdown"],
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
            domain_analysis=domain_analysis,
            quality_summary=quality_summary,
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
        has_description = bool((repo.get("description") or "").strip())
        has_license = bool(repo.get("license") and repo["license"].get("spdx_id"))
        has_homepage = bool((repo.get("homepage") or "").strip())
        has_wiki = bool(repo.get("has_wiki", False))
        stars = repo.get("stargazers_count", 0)
        forks = repo.get("forks_count", 0)
        watchers = repo.get("watchers_count", 0)
        topics = repo.get("topics") or []
        open_issues_count = repo.get("open_issues_count", 0)
        quality_score = round(
            (
                (1.0 if has_description else 0.0)
                + (1.0 if has_license else 0.0)
                + (1.0 if has_homepage else 0.0)
                + (1.0 if has_wiki else 0.0)
                + (1.0 if topics else 0.0)
                + min(stars / 100, 1.0)
                + min((watchers + forks) / 200, 1.0)
                - min(open_issues_count / 200, 0.5)
            )
            / 6.5
            * 100
        , 1)
        return RepositorySummary(
            name=repo["name"],
            full_name=repo["full_name"],
            url=repo["html_url"],
            description=repo.get("description"),
            stars=stars,
            forks=forks,
            language=repo.get("language"),
            is_fork=repo.get("fork", False),
            created_at=_parse_dt(repo.get("created_at")),
            updated_at=_parse_dt(repo.get("updated_at")),
            pushed_at=_parse_dt(repo.get("pushed_at")),
            topics=topics if isinstance(topics, list) else [],
            has_description=has_description,
            has_license=has_license,
            has_homepage=has_homepage,
            has_wiki=has_wiki,
            open_issues_count=open_issues_count,
            quality_score=max(0.0, min(100.0, quality_score)),
        )

    def _build_repo_quality_summary(
        self,
        repo_summaries: list[RepositorySummary],
        repos_raw: list[dict[str, Any]],
        now: datetime,
    ) -> dict[str, float | int]:
        total = len(repo_summaries)
        if total == 0:
            return {
                "repositories_with_license_percent": 0.0,
                "repositories_with_description_percent": 0.0,
                "repositories_with_homepage_percent": 0.0,
                "repositories_with_wiki_percent": 0.0,
                "repositories_with_topics_percent": 0.0,
                "archived_repositories_count": 0,
                "disabled_repositories_count": 0,
                "stale_repositories_180d_count": 0,
                "average_open_issues_per_repo": 0.0,
            }

        stale_180d = sum(
            1
            for r in repo_summaries
            if not r.pushed_at or _days_between(r.pushed_at, now) > 180
        )

        return {
            "repositories_with_license_percent": round(
                sum(1 for r in repo_summaries if r.has_license) / total * 100, 1
            ),
            "repositories_with_description_percent": round(
                sum(1 for r in repo_summaries if r.has_description) / total * 100, 1
            ),
            "repositories_with_homepage_percent": round(
                sum(1 for r in repo_summaries if r.has_homepage) / total * 100, 1
            ),
            "repositories_with_wiki_percent": round(
                sum(1 for r in repo_summaries if r.has_wiki) / total * 100, 1
            ),
            "repositories_with_topics_percent": round(
                sum(1 for r in repo_summaries if r.topics) / total * 100, 1
            ),
            "archived_repositories_count": sum(1 for repo in repos_raw if repo.get("archived")),
            "disabled_repositories_count": sum(1 for repo in repos_raw if repo.get("disabled")),
            "stale_repositories_180d_count": stale_180d,
            "average_open_issues_per_repo": round(
                statistics.mean([r.open_issues_count for r in repo_summaries]), 2
            ),
        }

    def _build_domain_analysis(
        self,
        *,
        repo_summaries: list[RepositorySummary],
        repos: list[dict[str, Any]],
        language_breakdown: dict[str, int],
    ) -> dict[str, Any]:
        scores = {domain: 0.0 for domain in DOMAIN_KEYWORDS}

        for language, count in language_breakdown.items():
            domain = LANGUAGE_DOMAIN_HINTS.get(language.lower())
            if domain:
                scores[domain] += count * 2.0

        for repo_summary, repo_raw in zip(repo_summaries, repos):
            text_parts = [
                repo_summary.name,
                repo_summary.full_name,
                repo_summary.description or "",
                " ".join(repo_summary.topics),
                (repo_raw.get("homepage") or ""),
            ]
            corpus = " ".join(text_parts).lower()
            repo_weight = 1.0 + min(repo_summary.stars / 1000, 2.5)

            for domain, keywords in DOMAIN_KEYWORDS.items():
                matches = sum(1 for keyword in keywords if keyword in corpus)
                if matches:
                    scores[domain] += matches * repo_weight

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_score = ranked[0][1] if ranked else 0.0
        total_score = sum(scores.values())
        primary_domain = ranked[0][0] if top_score > 0 else None
        confidence = round((top_score / total_score * 100), 1) if total_score > 0 else 0.0

        breakdown = {
            key: round((value / total_score * 100), 1)
            for key, value in ranked
            if total_score > 0 and value > 0
        }

        return {
            "primary_domain": primary_domain,
            "domain_confidence_percent": confidence,
            "domain_breakdown": breakdown,
        }

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
        domain_analysis: dict[str, Any],
        quality_summary: dict[str, float | int],
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

        if repo_stats.primary_domain:
            breakdown = domain_analysis.get("domain_breakdown", {})
            top_domains = list(breakdown.items())[:3]
            domain_readout = ", ".join(
                f"{name.replace('_', ' ')} ({score:.1f}%)" for name, score in top_domains
            )
            insights.append(
                ProfileInsight(
                    category="domain_intelligence",
                    title="Domain specialization",
                    description=(
                        f"Primary domain appears to be {repo_stats.primary_domain.replace('_', ' ')} "
                        f"with {repo_stats.domain_confidence_percent:.1f}% confidence. "
                        f"Signals: {domain_readout or 'insufficient domain signals'}."
                    ),
                    severity="info",
                )
            )

        license_pct = float(quality_summary["repositories_with_license_percent"])
        docs_pct = float(quality_summary["repositories_with_description_percent"])
        stale_count = int(quality_summary["stale_repositories_180d_count"])
        if repo_stats.total_repositories > 0:
            insights.append(
                ProfileInsight(
                    category="repo_quality",
                    title="Repository quality signals",
                    description=(
                        f"License coverage: {license_pct:.1f}%, descriptions: {docs_pct:.1f}%, "
                        f"stale repos (>180d): {stale_count}/{repo_stats.total_repositories}, "
                        f"avg open issues/repo: {repo_stats.average_open_issues_per_repo:.2f}."
                    ),
                    severity=(
                        "positive"
                        if license_pct >= 60 and stale_count <= max(1, repo_stats.total_repositories // 2)
                        else "neutral"
                    ),
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
