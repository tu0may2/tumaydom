"""Провайдеры LLM: Anthropic и любой OpenAI-совместимый эндпоинт.

Бесплатные варианты (Gemini, Groq, OpenRouter, локальная Ollama) говорят по
протоколу OpenAI, поэтому под них хватает одного класса с другим `base_url`.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

log = logging.getLogger(__name__)

Image = tuple[str, str]  # (base64, media_type)

# Готовые пресеты: base_url и модель по умолчанию.
PRESETS: dict[str, dict[str, str]] = {
    "anthropic": {"model": "claude-opus-5", "base_url": ""},
    "gemini": {
        "model": "gemini-2.5-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    },
    "groq": {
        "model": "llama-3.3-70b-versatile",
        "base_url": "https://api.groq.com/openai/v1",
    },
    "openrouter": {
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "base_url": "https://openrouter.ai/api/v1",
    },
    "mistral": {"model": "mistral-large-latest", "base_url": "https://api.mistral.ai/v1"},
    "openai": {"model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
    "ollama": {"model": "llama3.1", "base_url": "http://localhost:11434/v1"},
}

# У кого из бесплатных провайдеров есть разбор картинок (скриншоты выкладок).
VISION_CAPABLE = {"anthropic", "gemini", "openai", "openrouter", "mistral"}


class LLMProvider(ABC):
    """Общий интерфейс: свободный текст и JSON по схеме."""

    name: str
    model: str

    @abstractmethod
    def text(self, prompt: str, *, system: str, images: list[Image] | None = None,
             effort: str = "high", max_tokens: int = 16000) -> str:
        ...

    @abstractmethod
    def json(self, prompt: str, *, system: str, schema: dict[str, Any],
             images: list[Image] | None = None, effort: str = "low",
             max_tokens: int = 16000) -> dict[str, Any]:
        ...

    @property
    def supports_vision(self) -> bool:
        return self.name in VISION_CAPABLE


class AnthropicProvider(LLMProvider):
    """Claude через официальный SDK."""

    name = "anthropic"

    def __init__(self, api_key: str | None, model: str) -> None:
        import anthropic

        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key or None)

    def _content(self, prompt: str, images: list[Image] | None) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = [
            {"type": "image",
             "source": {"type": "base64", "media_type": media_type, "data": data}}
            for data, media_type in images or []
        ]
        blocks.append({"type": "text", "text": prompt})
        return blocks

    def text(self, prompt: str, *, system: str, images: list[Image] | None = None,
             effort: str = "high", max_tokens: int = 16000) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=[{"role": "user", "content": self._content(prompt, images)}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("Модель отказалась отвечать на этот запрос")
        return "\n".join(b.text for b in response.content if b.type == "text").strip()

    def json(self, prompt: str, *, system: str, schema: dict[str, Any],
             images: list[Image] | None = None, effort: str = "low",
             max_tokens: int = 16000) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort,
                           "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": self._content(prompt, images)}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("Модель отказалась отвечать на этот запрос")
        raw = next(b.text for b in response.content if b.type == "text")
        return json.loads(raw)


class OpenAICompatProvider(LLMProvider):
    """Любой эндпоинт с протоколом OpenAI: Gemini, Groq, OpenRouter, Ollama.

    Строгие JSON-схемы поддерживают не все, поэтому есть каскад:
    `json_schema` → `json_object` → выдёргивание JSON из текста.
    """

    def __init__(self, name: str, api_key: str | None, model: str, base_url: str) -> None:
        from openai import OpenAI

        self.name = name
        self.model = model
        # Ollama ключ не проверяет, но клиент требует непустую строку.
        self._client = OpenAI(api_key=api_key or "not-needed", base_url=base_url or None)

    def _messages(self, prompt: str, system: str,
                  images: list[Image] | None) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [
            {"type": "image_url",
             "image_url": {"url": f"data:{media_type};base64,{data}"}}
            for data, media_type in images or []
        ]
        content.append({"type": "text", "text": prompt})
        return [{"role": "system", "content": system}, {"role": "user", "content": content}]

    def text(self, prompt: str, *, system: str, images: list[Image] | None = None,
             effort: str = "high", max_tokens: int = 16000) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=self._messages(prompt, system, images),
        )
        return (response.choices[0].message.content or "").strip()

    def json(self, prompt: str, *, system: str, schema: dict[str, Any],
             images: list[Image] | None = None, effort: str = "low",
             max_tokens: int = 16000) -> dict[str, Any]:
        hint = (
            f"{prompt}\n\nОтветь СТРОГО одним JSON-объектом по схеме, без пояснений "
            f"и без markdown-ограждений. Схема:\n{json.dumps(schema, ensure_ascii=False)}"
        )
        messages = self._messages(hint, system, images)

        formats: list[dict[str, Any] | None] = [
            {"type": "json_schema",
             "json_schema": {"name": "result", "strict": True, "schema": schema}},
            {"type": "json_object"},
            None,
        ]

        last_error: Exception | None = None
        for response_format in formats:
            kwargs: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens,
                                      "messages": messages}
            if response_format:
                kwargs["response_format"] = response_format
            try:
                response = self._client.chat.completions.create(**kwargs)
                return extract_json(response.choices[0].message.content or "")
            except Exception as exc:  # провайдер не умеет этот режим — пробуем проще
                last_error = exc
                log.warning("Провайдер %s отклонил режим %s: %s", self.name,
                            (response_format or {}).get("type", "plain"), exc)

        raise RuntimeError(f"Не удалось получить JSON от провайдера {self.name}") from last_error


def extract_json(raw: str) -> dict[str, Any]:
    """Достать объект даже если модель обернула его в ```json или пояснения."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start, depth = None, 0
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start:index + 1])
                except json.JSONDecodeError:
                    start = None
    raise ValueError(f"В ответе модели нет корректного JSON: {raw[:200]}")


def build_provider(name: str, api_key: str, model: str = "", base_url: str = "") -> LLMProvider:
    name = (name or "anthropic").lower()
    preset = PRESETS.get(name)
    if preset is None:
        raise ValueError(
            f"Неизвестный провайдер '{name}'. Доступны: {', '.join(sorted(PRESETS))}. "
            "Для своего эндпоинта используй FITCOACH_PROVIDER=openai и FITCOACH_BASE_URL."
        )

    model = model or preset["model"]
    base_url = base_url or preset["base_url"]

    if name == "anthropic":
        return AnthropicProvider(api_key, model)
    return OpenAICompatProvider(name, api_key, model, base_url)
