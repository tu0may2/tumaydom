"""Конфигурация приложения (читается из окружения / .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_owner_chat_id: int | None = Field(default=None, alias="TELEGRAM_OWNER_CHAT_ID")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    model: str = Field(default="claude-opus-5", alias="FITCOACH_MODEL")

    db_path: Path = Field(default=Path("data/fitcoach.db"), alias="FITCOACH_DB_PATH")
    timezone: str = Field(default="Europe/Moscow", alias="FITCOACH_TIMEZONE")

    morning_time: str = Field(default="07:30", alias="FITCOACH_MORNING_TIME")
    weekly_day: str = Field(default="sun", alias="FITCOACH_WEEKLY_DAY")
    weekly_time: str = Field(default="19:00", alias="FITCOACH_WEEKLY_TIME")

    def hhmm(self, value: str) -> tuple[int, int]:
        hours, minutes = value.split(":")
        return int(hours), int(minutes)


@lru_cache
def get_settings() -> Settings:
    return Settings()
