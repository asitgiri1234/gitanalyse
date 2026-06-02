class AppError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 500,
        error_code: str = "internal_error",
        extra: dict | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.extra = extra or {}
        super().__init__(message)


class ProfileNotFoundError(AppError):
    def __init__(self, username: str) -> None:
        super().__init__(
            f"GitHub user '{username}' was not found.",
            status_code=404,
            error_code="profile_not_found",
            extra={"username": username},
        )


class InvalidUsernameError(AppError):
    def __init__(self, username: str, reason: str | None = None) -> None:
        detail = reason or f"Invalid GitHub username: '{username}'."
        super().__init__(
            detail,
            status_code=400,
            error_code="invalid_username",
            extra={"username": username},
        )


class GitHubAPIError(AppError):
    def __init__(self, message: str, *, status_code: int = 502, extra: dict | None = None) -> None:
        super().__init__(
            message,
            status_code=status_code,
            error_code="github_api_error",
            extra=extra,
        )


class AnalysisNotFoundError(AppError):
    def __init__(self, username: str) -> None:
        super().__init__(
            f"No stored analysis for '{username}'. Use POST /api/profiles/analyze first.",
            status_code=404,
            error_code="analysis_not_found",
            extra={"username": username},
        )


class RateLimitError(AppError):
    def __init__(self, reset_at: str | None = None) -> None:
        super().__init__(
            "GitHub API rate limit exceeded. Try again later or provide a GITHUB_TOKEN.",
            status_code=503,
            error_code="rate_limit_exceeded",
            extra={"reset_at": reset_at} if reset_at else {},
        )
