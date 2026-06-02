from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProfileAnalysis(Base):
    __tablename__ = "profile_analyses"
    __table_args__ = (UniqueConstraint("username", name="uq_username"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    profile_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    company: Mapped[str | None] = mapped_column(String(512), nullable=True)
    blog: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    followers_count: Mapped[int] = mapped_column(Integer, default=0)
    following_count: Mapped[int] = mapped_column(Integer, default=0)
    public_repo_count: Mapped[int] = mapped_column(Integer, default=0)

    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    account_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    total_stars_received: Mapped[int] = mapped_column(Integer, default=0)
    total_forks_received: Mapped[int] = mapped_column(Integer, default=0)
    total_watchers: Mapped[int] = mapped_column(Integer, default=0)

    most_starred_repo_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    most_starred_repo_stars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    most_starred_repo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # JSON blobs for richer analysis
    repository_stats_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    language_breakdown_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    insights_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    top_repositories_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    source: Mapped[str] = mapped_column(String(32), default="github_api")
