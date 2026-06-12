"""Bootstrap konfiguratsiya (pydantic-settings).

.env FAQAT tizimni ko'tarish uchun: DB ulanishi, Fernet master kalit, JWT imzo,
birinchi admin. Qolgan (API kalit, TG token, modellar, chegaralar) admin-paneldagi
Secrets sahifasidan dinamik boshqariladi — bu yerdagilar shunchaki fallback default.
Resolver tartibi (secrets.py'da): DB secrets > .env(Settings) > kod default.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ── Bootstrap (faqat .env) ──────────────────────────────────────────────
    db_dsn: str = Field("sqlite:///orchestra.db", alias="DB_DSN")
    secret_enc_key: str = Field("", alias="SECRET_ENC_KEY")
    web_jwt_secret: str = Field("change-me-please", alias="WEB_JWT_SECRET")
    bootstrap_admin_user: str = Field("admin", alias="BOOTSTRAP_ADMIN_USER")
    bootstrap_admin_pass: str = Field("", alias="BOOTSTRAP_ADMIN_PASS")

    web_host: str = Field("0.0.0.0", alias="WEB_HOST")
    web_port: int = Field(8000, alias="WEB_PORT")

    # ── Dinamik default'lar (odatda Secrets sahifasidan ustun yoziladi) ──────
    poll_interval: float = Field(2.0, alias="POLL_INTERVAL")
    max_retry: int = Field(2, alias="MAX_RETRY")
    max_parallel: int = Field(5, alias="MAX_PARALLEL")
    planner_model: str = Field("claude-opus-4-8", alias="PLANNER_MODEL")
    executor_model: str = Field("claude-sonnet-4-6", alias="EXECUTOR_MODEL")
    reviewer_model: str = Field("claude-sonnet-4-6", alias="REVIEWER_MODEL")
    chat_model: str = Field("claude-sonnet-4-6", alias="CHAT_MODEL")
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    tg_bot_token: str = Field("", alias="TG_BOT_TOKEN")
    tg_chat_id: str = Field("", alias="TG_CHAT_ID")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
