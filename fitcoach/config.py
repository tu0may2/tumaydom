"""Конфигурация приложения (читается из окружения / .env)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Откуда брать ключ, если FITCOACH_API_KEY не задан явно.
PROVIDER_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openai": "OPENAI_API_KEY",
    "ollama": "",  # локальная модель, ключ не нужен
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_owner_chat_id: int | None = Field(default=None, alias="TELEGRAM_OWNER_CHAT_ID")

    provider: str = Field(default="ollama", alias="FITCOACH_PROVIDER")
    api_key: str = Field(default="", alias="FITCOACH_API_KEY")
    model: str = Field(default="", alias="FITCOACH_MODEL")
    base_url: str = Field(default="", alias="FITCOACH_BASE_URL")
    vision: str = Field(default="auto", alias="FITCOACH_VISION")  # auto | on | off
    request_timeout: float = Field(default=600.0, alias="FITCOACH_TIMEOUT")

    db_path: Path = Field(default=Path("data/fitcoach.db"), alias="FITCOACH_DB_PATH")
    timezone: str = Field(default="Europe/Moscow", alias="FITCOACH_TIMEZONE")

    morning_time: str = Field(default="07:30", alias="FITCOACH_MORNING_TIME")
    weekly_day: str = Field(default="sun", alias="FITCOACH_WEEKLY_DAY")
    weekly_time: str = Field(default="19:00", alias="FITCOACH_WEEKLY_TIME")

    @model_validator(mode="after")
    def _resolve_api_key(self) -> "Settings":
        """Ключ можно задать и как FITCOACH_API_KEY, и как родное имя провайдера."""
        self.provider = self.provider.lower().strip()
        self.vision = self.vision.lower().strip() or "auto"
        if not self.api_key:
            env_name = PROVIDER_KEY_ENV.get(self.provider, "")
            if env_name:
                self.api_key = os.getenv(env_name, "")
        return self

    def hhmm(self, value: str) -> tuple[int, int]:
        hours, minutes = value.split(":")
        return int(hours), int(minutes)


@lru_cache
def get_settings() -> Settings:
    return Settings()
