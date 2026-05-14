from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    project_name: str = "Democracy Index Tracker"
    database_url: str = "sqlite:///./data/tracker.db"
    redis_url: str = "redis://redis:6379/0"
    secret_key: str = "dev-secret-key-replace-in-production"
    access_token_expire_minutes: int = 30


settings = Settings()
