"""Фасад над провайдером LLM: текст и JSON по схеме, с картинками или без."""

from __future__ import annotations

import logging
from typing import Any

from .config import Settings, get_settings
from .providers import Image, LLMProvider, build_provider

log = logging.getLogger(__name__)

# Effort по задачам: разбор входных данных дешёвый, стратегия — дорогая.
# У провайдеров без управления «усилием» параметр просто игнорируется.
EFFORT_EXTRACT = "low"
EFFORT_ANALYSIS = "high"


class LLM:
    def __init__(self, settings: Settings | None = None,
                 provider: LLMProvider | None = None) -> None:
        settings = settings or get_settings()
        self.provider = provider or build_provider(
            settings.provider,
            settings.api_key,
            settings.model,
            settings.base_url,
            settings.vision,
            settings.request_timeout,
        )
        self.model = self.provider.model

    @property
    def supports_vision(self) -> bool:
        return self.provider.supports_vision

    def text(self, prompt: str, *, system: str, images: list[Image] | None = None,
             effort: str = EFFORT_ANALYSIS, max_tokens: int = 16000) -> str:
        return self.provider.text(prompt, system=system, images=images,
                                  effort=effort, max_tokens=max_tokens)

    def json(self, prompt: str, *, system: str, schema: dict[str, Any],
             images: list[Image] | None = None, effort: str = EFFORT_EXTRACT,
             max_tokens: int = 16000) -> dict[str, Any]:
        return self.provider.json(prompt, system=system, schema=schema, images=images,
                                  effort=effort, max_tokens=max_tokens)
