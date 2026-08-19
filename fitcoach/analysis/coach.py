"""Сценарии тренера: разбор тренировки, утренний дайджест, недельная стратегия."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from ..db import Database
from ..llm import LLM, EFFORT_ANALYSIS
from ..prompts import coach_system, load
from ..schemas import PLAN_SCHEMA
from .stats import build_context, render_context, week_start

log = logging.getLogger(__name__)


def analyze_workout(llm: LLM, db: Database, user_id: int, workout: dict[str, Any]) -> str:
    """Короткий разбор только что присланной тренировки."""
    context = build_context(db, user_id)
    prompt = (
        f"{load('analysis')}\n\n"
        f"Только что присланная тренировка:\n{render_context(workout)}\n\n"
        f"История и контекст:\n{render_context(context)}"
    )
    return llm.text(prompt, system=coach_system(), effort=EFFORT_ANALYSIS, max_tokens=4000)


def morning_digest(llm: LLM, db: Database, user_id: int) -> str:
    """Утреннее сообщение: план дня, восстановление, питание."""
    context = build_context(db, user_id)
    prompt = f"{load('morning')}\n\nКонтекст:\n{render_context(context)}"
    text = llm.text(prompt, system=coach_system(), effort=EFFORT_ANALYSIS, max_tokens=4000)
    db.log_message(user_id, "morning", text)
    return text


def weekly_review(llm: LLM, db: Database, user_id: int) -> tuple[str, dict[str, Any]]:
    """Недельный разбор + новый план. Возвращает (текст, план) и сохраняет план."""
    context = build_context(db, user_id, days=56)
    next_week = (week_start() + timedelta(days=7)).isoformat()

    review = llm.text(
        f"{load('weekly')}\n\nСделай сейчас только Часть 1 — разбор.\n\n"
        f"Контекст:\n{render_context(context)}",
        system=coach_system(),
        effort=EFFORT_ANALYSIS,
        max_tokens=4000,
    )

    plan = llm.json(
        f"{load('weekly')}\n\nСделай сейчас только Часть 2 — план на неделю, "
        f"начинающуюся {next_week}.\n\n"
        f"Твой разбор недели:\n{review}\n\nКонтекст:\n{render_context(context)}",
        system=coach_system(),
        schema=PLAN_SCHEMA,
        effort=EFFORT_ANALYSIS,
    )

    db.save_plan(user_id, plan.get("week_start") or next_week, plan, plan.get("rationale"))
    db.log_message(user_id, "weekly", review)
    return review, plan


def answer_question(llm: LLM, db: Database, user_id: int, question: str) -> str:
    """Свободный вопрос: питание, техника, корректировка плана."""
    context = build_context(db, user_id)
    prompt = (
        f"Вопрос спортсмена:\n{question}\n\n"
        f"Отвечай с опорой на его данные. Контекст:\n{render_context(context)}"
    )
    text = llm.text(prompt, system=coach_system(), effort=EFFORT_ANALYSIS, max_tokens=4000)
    db.log_message(user_id, "chat", text)
    return text


def today_session(db: Database, user_id: int) -> dict[str, Any] | None:
    """Сессия из сохранённого плана на сегодня (для напоминаний)."""
    plan = db.get_plan(user_id)
    if not plan:
        return None
    weekday = date.today().strftime("%a").lower()[:3]
    for day in plan.get("days") or []:
        if day.get("weekday") == weekday:
            return day
    return None
