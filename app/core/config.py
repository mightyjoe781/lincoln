from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/lincoln"
    upload_dir: str = "/tmp/lincoln_uploads"
    max_upload_size_bytes: int = 20 * 1024 * 1024  # 20 MB
    allowed_mime_types: list[str] = ["application/pdf", "text/csv", "application/octet-stream"]
    redis_url: str = "redis://localhost:6379/0"
    environment: str = "development"
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30


settings = Settings()
