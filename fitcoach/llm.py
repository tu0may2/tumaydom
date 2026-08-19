"""Тонкая обёртка над Anthropic SDK: текст и JSON по схеме."""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from .config import get_settings

log = logging.getLogger(__name__)

# Effort по задачам: разбор входных данных дешёвый, стратегия — дорогая.
EFFORT_EXTRACT = "low"
EFFORT_ANALYSIS = "high"


class LLM:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.model
        self._client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key or None)

    def text(
        self,
        prompt: str | list[dict[str, Any]],
        *,
        system: str,
        effort: str = EFFORT_ANALYSIS,
        max_tokens: int = 16000,
    ) -> str:
        """Свободный текстовый ответ (дайджест, разбор, совет)."""
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("Модель отказалась отвечать на этот запрос")
        return "\n".join(b.text for b in response.content if b.type == "text").strip()

    def json(
        self,
        prompt: str | list[dict[str, Any]],
        *,
        system: str,
        schema: dict[str, Any],
        effort: str = EFFORT_EXTRACT,
        max_tokens: int = 16000,
    ) -> dict[str, Any]:
        """Ответ, гарантированно валидный по JSON-схеме."""
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("Модель отказалась отвечать на этот запрос")
        raw = next(b.text for b in response.content if b.type == "text")
        return json.loads(raw)


def image_block(data_b64: str, media_type: str = "image/jpeg") -> dict[str, Any]:
    """Блок с картинкой для vision-запроса (скриншот из Garmin Connect и т.п.)."""
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data_b64},
    }
