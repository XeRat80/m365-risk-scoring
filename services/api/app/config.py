from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_TOKEN_ENCRYPTION_KEY = "Y2hhbmdlLW1lLWNoYW5nZS1tZS1jaGFuZ2UtbWU="


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    connector_mode: str = "mock"
    database_url: str = "postgresql+asyncpg://m365risk:m365risk@localhost:5432/m365risk"
    database_admin_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/m365risk"
    mock_graph_url: str = "http://localhost:8081"
    oidc_issuer: str = "http://localhost:8081"
    oidc_jwks_url: str | None = None
    oidc_audience: str = "m365-risk-api"
    oidc_admin_role: str = "M365Risk.Admin"
    oidc_analyst_role: str = "M365Risk.Analyst"
    mock_admin_secret: str = "local-admin-secret-change-me"
    token_encryption_key: str = Field(min_length=32)
    pseudonymization_key: str = Field(
        default="local-pseudonymization-key-change-me", min_length=32
    )
    metrics_key: str = Field(default="local-metrics-key-change-me", min_length=24)
    model_dir: str = "artifacts/models/current"
    sync_interval_seconds: int = 5
    graph_client_id: str | None = None
    graph_client_secret: str | None = None
    graph_redirect_uri: str = "http://localhost:8000/api/v1/tenants/onboarding/callback"
    otel_exporter_otlp_endpoint: str | None = None

    @field_validator("connector_mode")
    @classmethod
    def validate_connector(cls, value: str) -> str:
        if value not in {"mock", "real"}:
            raise ValueError("connector_mode must be mock or real")
        return value

    def model_post_init(self, __context: object) -> None:
        if self.app_env == "production":
            if self.connector_mode == "mock":
                raise ValueError("mock connector is forbidden in production")
            if "change-me" in self.mock_admin_secret:
                raise ValueError("default secrets are forbidden in production")
            if "change-me" in self.metrics_key:
                raise ValueError("default metrics secret is forbidden in production")
            if self.token_encryption_key == DEFAULT_TOKEN_ENCRYPTION_KEY:
                raise ValueError("default encryption key is forbidden in production")
            if "change-me" in self.pseudonymization_key:
                raise ValueError("default pseudonymization key is forbidden in production")
            if not self.graph_client_id or not self.graph_client_secret:
                raise ValueError("Graph application credentials are required in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
