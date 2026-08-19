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
