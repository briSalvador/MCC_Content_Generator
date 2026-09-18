from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Cyber Awareness Platform"
    environment: str = "development"
    database_url: str = "sqlite:///./cyber_awareness.db"
    mock_ai_services: bool = True
    mock_email_service: bool = True
    dev_auth_bypass: bool = True

    entra_tenant_id: str = ""
    entra_api_client_id: str = ""
    entra_client_secret: str = ""
    entra_redirect_uri: str = "http://localhost:8000/auth/callback"
    entra_post_logout_redirect_uri: str = "http://localhost:8000/"
    session_secret: str = "replace-with-at-least-32-random-characters"
    session_cookie_secure: bool = False
    session_max_age_seconds: int = 3600

    database_auth_mode: Literal["password", "entra"] = "password"
    azure_database_scope: str = (
        "https://ossrdbms-aad.database.windows.net/.default"
    )

    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_text_deployment: str = "cyber-text"
    azure_openai_image_deployment: str = "cyber-poster"
    azure_openai_image_size: str = "1024x1536"
    azure_openai_image_quality: Literal["low", "medium", "high", "auto"] = "high"
    azure_openai_timeout_seconds: int = 600

    graph_sender_mailbox: str = "securityawareness@example.com"

    poster_storage_path: str = "./generated_posters"
    max_poster_image_bytes: int = 2_500_000

    max_recipients_per_campaign: int = 500
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 30

    @property
    def entra_issuer(self) -> str:
        return f"https://login.microsoftonline.com/{self.entra_tenant_id}/v2.0"

    @property
    def entra_authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.entra_tenant_id}"

    @property
    def entra_jwks_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.entra_tenant_id}/discovery/v2.0/keys"

    @property
    def entra_web_login_configured(self) -> bool:
        return bool(
            self.entra_tenant_id
            and self.entra_api_client_id
            and self.entra_client_secret
            and self.entra_redirect_uri
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
