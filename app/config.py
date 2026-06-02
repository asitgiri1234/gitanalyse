from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    github_token: str | None = None
    database_url: str = "sqlite:///./data/gitanalyse.db"
    github_api_base: str = "https://api.github.com"
    request_timeout: float = 30.0


settings = Settings()
