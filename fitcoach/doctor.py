"""Проверка окружения: `python -m fitcoach.doctor`.

Отвечает на вопрос «почему бот молчит»: виден ли провайдер, скачана ли модель,
умеет ли она JSON и картинки, хватает ли контекста.
"""

from __future__ import annotations

import base64
import json
import sys

from dotenv import load_dotenv

from .config import get_settings
from .llm import LLM
from .providers import PRESETS

OK, FAIL, WARN = "[ ok ]", "[fail]", "[warn]"

# Минимальная валидная картинка (PNG 1×1) — проверить, что vision не падает.
PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)

PROBE_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "note": {"type": "string"}},
    "required": ["ok", "note"],
    "additionalProperties": False,
}


def main() -> int:
    load_dotenv()
    settings = get_settings()
    failures = 0

    print(f"Провайдер: {settings.provider}")
    if settings.provider not in PRESETS:
        print(f"{FAIL} неизвестный провайдер, доступны: {', '.join(sorted(PRESETS))}")
        return 1

    needs_key = settings.provider != "ollama"
    if needs_key and not settings.api_key:
        print(f"{FAIL} ключ не найден — заполни FITCOACH_API_KEY в .env")
        failures += 1
    elif needs_key:
        print(f"{OK} ключ найден ({settings.api_key[:6]}…)")

    try:
        llm = LLM(settings)
    except Exception as exc:
        print(f"{FAIL} не удалось создать клиента: {exc}")
        return 1

    print(f"Модель: {llm.model}")
    print(f"Vision: {'да' if llm.supports_vision else 'нет'} (FITCOACH_VISION={settings.vision})")

    # 1. Простой запрос — жив ли эндпоинт и скачана ли модель.
    try:
        answer = llm.text("Ответь одним словом: привет", system="Ты отвечаешь кратко.",
                          max_tokens=64)
        print(f"{OK} текстовый запрос прошёл: {answer[:60]!r}")
    except Exception as exc:
        print(f"{FAIL} текстовый запрос не прошёл: {exc}")
        _hint(settings.provider, exc)
        return 1

    # 2. JSON — на нём держится весь разбор входящих сообщений.
    try:
        result = llm.json(
            'Верни объект с полями ok=true и note="проверка".',
            system="Ты возвращаешь только JSON.",
            schema=PROBE_SCHEMA,
        )
        print(f"{OK} JSON-режим работает: {json.dumps(result, ensure_ascii=False)}")
    except Exception as exc:
        print(f"{FAIL} JSON-режим не работает: {exc}")
        print("       разбор тренировок из текста работать не будет — возьми модель посильнее")
        failures += 1

    # 3. Картинки — нужны для скриншотов выкладок.
    if llm.supports_vision:
        try:
            encoded = base64.standard_b64encode(PIXEL_PNG).decode()
            llm.text("Что на картинке? Ответь одним словом.",
                     system="Ты отвечаешь кратко.",
                     images=[(encoded, "image/png")], max_tokens=64)
            print(f"{OK} картинки принимаются")
        except Exception as exc:
            print(f"{FAIL} картинки не принимаются: {exc}")
            print("       поставь FITCOACH_VISION=off или возьми модель с vision")
            failures += 1
    else:
        print(f"{WARN} модель без vision — скриншоты выкладок придётся пересказывать текстом")

    if settings.provider == "ollama":
        print(f"{WARN} проверь контекст: OLLAMA_CONTEXT_LENGTH должен быть >= 16384, "
              "иначе история тренировок молча обрежется")

    if not settings.telegram_bot_token:
        print(f"{FAIL} TELEGRAM_BOT_TOKEN не задан")
        failures += 1
    else:
        print(f"{OK} токен Telegram на месте")

    print("\nГотово." if not failures else f"\nПроблем: {failures}")
    return 1 if failures else 0


def _hint(provider: str, exc: Exception) -> None:
    text = str(exc).lower()
    if provider == "ollama":
        if "connect" in text or "refused" in text:
            print("       Ollama не отвечает — запусти `ollama serve`")
        elif "not found" in text:
            print("       модель не скачана — выполни `ollama pull <модель>`")
    elif "api key" in text or "401" in text or "403" in text:
        print("       ключ неверный или без доступа к этой модели")
    elif "429" in text or "quota" in text:
        print("       упёрся в бесплатный лимит — подожди или смени провайдера")


if __name__ == "__main__":
    sys.exit(main())
