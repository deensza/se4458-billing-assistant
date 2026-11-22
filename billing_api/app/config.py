from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (or a local .env file)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://billing:billing@localhost:5432/billing"

    # JWT (HS256). The same secret/issuer is configured on the API Gateway (Kong jwt plugin).
    jwt_secret: str = "local-dev-secret-change-me-0123456789abcdef"
    jwt_issuer: str = "se4458-billing-auth"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    bcrypt_rounds: int = 12

    # Origin protection: when set, every request except /health must carry the header
    # X-Gateway-Secret with this value. Only the API Gateway (Kong) adds it, so the API
    # cannot be called directly, bypassing the gateway. Empty = disabled (unit tests).
    gateway_shared_secret: str = ""

    # Create tables and load demo data when the service starts.
    init_db_on_startup: bool = True
    seed_demo_data: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
