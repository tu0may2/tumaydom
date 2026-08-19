"""Разбор входящих сообщений: текст, скриншоты, файлы выгрузок."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from ..db import Database
from ..llm import LLM, EFFORT_EXTRACT
from ..prompts import load
from ..schemas import INGEST_SCHEMA

log = logging.getLogger(__name__)

EMPTY: dict[str, Any] = {
    "intent": "unknown",
    "confidence": 0.0,
    "workouts": [],
    "sleep": [],
    "metrics": [],
    "profile_patch": {},
    "comment": "",
}


def parse_message(
    llm: LLM,
    *,
    text: str | None = None,
    images: list[tuple[str, str]] | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Вернуть структурированное представление сообщения.

    `images` — список пар (base64, media_type) для скриншотов выгрузок.
    """
    today = today or date.today().isoformat()
    if images and not llm.supports_vision:
        raise ValueError(
            f"Провайдер {llm.provider.name} не умеет читать картинки — "
            "перескажи выкладку текстом или переключись на провайдера с vision."
        )

    prompt = f"Сегодня {today}.\n\nСообщение пользователя:\n{text or ''}"
    result = llm.json(
        prompt,
        system=load("ingest"),
        schema=INGEST_SCHEMA,
        images=images,
        effort=EFFORT_EXTRACT,
    )
    return {**EMPTY, **result}


def apply_ingest(db: Database, user_id: int, parsed: dict[str, Any], *, source: str,
                 raw: str | None = None) -> dict[str, int]:
    """Сохранить распознанные сущности. Возвращает счётчики по типам."""
    counts = {"workouts": 0, "sleep": 0, "metrics": 0, "profile": 0}

    for workout in parsed.get("workouts") or []:
        db.add_workout(user_id, workout, source=source, raw=raw)
        counts["workouts"] += 1

    for night in parsed.get("sleep") or []:
        db.add_sleep(user_id, night, source=source, raw=raw)
        counts["sleep"] += 1

    for metric in parsed.get("metrics") or []:
        if metric.get("name") and metric.get("value") is not None:
            db.add_metric(user_id, metric["name"], metric["value"], metric.get("date"))
            counts["metrics"] += 1

    patch = {k: v for k, v in (parsed.get("profile_patch") or {}).items() if v is not None}
    if patch:
        db.update_profile(user_id, patch)
        counts["profile"] = len(patch)

    return counts


QUESTION_WORDS = ("что", "как", "почему", "зачем", "когда", "сколько", "какой", "какая",
                  "какие", "стоит ли", "можно", "нужно", "посоветуй", "подскажи", "объясни",
                  "сможешь", "умеешь", "а если", "лучше")

# Приветствия и короткие подтверждения: отвечаем сразу, без модели.
GREETINGS = {"привет", "приветик", "здравствуй", "здравствуйте", "хай", "ку", "йо",
             "hi", "hello", "здорово", "доброе утро", "добрый день", "добрый вечер",
             "спасибо", "спс", "ок", "окей", "ага", "понял", "поняла", "хорошо",
             "давай", "начнём", "начнем", "старт", "тест", "проверка"}

# Слова, после которых сообщение точно надо разбирать целиком, даже без цифр.
DATA_WORDS = ("цель", "вес", "рост", "возраст", "трениру", "зал", "дом", "гантел",
              "штанг", "турник", "травм", "колен", "спин", "плеч", "сплю", "спал",
              "сон", "бег", "жим", "присед", "тяга", "подход", "подтяг", "отжим",
              "питан", "ем ", "диет", "белок", "калор", "пульс", "растяж", "кардио")

SHORT_MESSAGE_WORDS = 8


def is_greeting(text: str) -> bool:
    """Приветствие или короткое «ок» — ответить можно без модели."""
    cleaned = text.strip().lower().strip("!.,…-—?)( ")
    return bool(cleaned) and cleaned in GREETINGS


def looks_like_question(text: str) -> bool:
    """Похоже на разговор, а не на данные тренировки.

    Такие сообщения идут одним запросом к модели вместо двух — на локальной
    модели это половина времени ожидания. Цифры и слова про тренировки, тело
    или питание всегда отправляют сообщение в полный разбор, чтобы не потерять
    данные для дневника.
    """
    stripped = text.strip().lower()
    if not stripped or any(char.isdigit() for char in stripped):
        return False
    if any(word in stripped for word in DATA_WORDS):
        return False
    if stripped.endswith("?") or any(stripped.startswith(w) for w in QUESTION_WORDS):
        return True
    # Короткая реплика без цифр и без «дневниковых» слов — это болтовня.
    return len(stripped.split()) <= SHORT_MESSAGE_WORDS
