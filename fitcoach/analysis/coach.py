"""Сценарии тренера: разбор тренировки, утренний дайджест, недельная стратегия."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from ..db import Database
from ..llm import LLM, EFFORT_ANALYSIS
from ..prompts import coach_system, load
from ..schemas import PLAN_SCHEMA
from .progress import cardio_progress, compare_workout, exercise_progress
from .stats import build_context, render_context, week_start

log = logging.getLogger(__name__)


def analyze_workout(llm: LLM, db: Database, user_id: int, workout: dict[str, Any]) -> str:
    """Разбор присланной тренировки: подходы, 1ПМ, темп, рекорды."""
    context = build_context(db, user_id)

    # Сравниваем с прошлым, исключив только что сохранённую сессию.
    history = [
        old for old in db.recent_workouts(user_id, days=365)
        if not (old.get("date") == workout.get("date")
                and old.get("title") == workout.get("title"))
    ]
    comparison = compare_workout(history, workout)

    prompt = (
        f"{load('analysis')}\n\n"
        f"Только что присланная тренировка:\n{render_context(workout)}\n\n"
        f"Сравнение с прошлыми (посчитано, не пересчитывай):\n"
        f"{render_context(comparison)}\n\n"
        f"Общий контекст:\n{render_context(context)}"
    )
    return llm.text(prompt, system=coach_system(), effort=EFFORT_ANALYSIS, max_tokens=4000)


def progress_report(db: Database, user_id: int, days: int = 180) -> str:
    """Сводка прогресса без обращения к модели — быстро и всегда точно."""
    workouts = db.recent_workouts(user_id, days=days)
    strength = exercise_progress(workouts)
    cardio = cardio_progress(workouts)

    if not strength and not cardio:
        return "Данных пока нет. Пришли пару тренировок, и здесь появится динамика."

    lines: list[str] = []
    if strength:
        lines.append("Силовые (оценка 1ПМ):")
        for row in strength[:12]:
            if row["sessions"] < 2:
                lines.append(f"— {row['exercise']}: {row['best_set']}, "
                             f"1ПМ ≈ {row['last_e1rm']} (одна сессия)")
                continue
            sign = "+" if row["change_kg"] >= 0 else ""
            lines.append(
                f"— {row['exercise']}: {row['first_e1rm']} → {row['last_e1rm']} кг "
                f"({sign}{row['change_kg']}, {sign}{row['change_pct']}%), "
                f"лучший подход {row['best_set']}, сессий {row['sessions']}"
            )
    if cardio:
        if lines:
            lines.append("")
        lines.append("Кардио (темп на км):")
        for row in cardio:
            change = row["change_sec_km"]
            direction = ("быстрее" if change < 0 else "медленнее") if change else "без изменений"
            lines.append(
                f"— {row['bucket']}: сейчас {row['last_pace']}, лучший {row['best_pace']} "
                f"({row['best_date']}), за период {abs(change)} с/км {direction}"
            )
    return "\n".join(lines)


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
    """Свободный вопрос: питание, техника, корректировка плана.

    В промпт идут последние реплики диалога, чтобы можно было спрашивать
    «а если наоборот?» и не пересказывать всё заново.
    """
    context = build_context(db, user_id)
    history = db.recent_dialog(user_id)

    parts = []
    if history:
        rendered = "\n".join(
            f"{'Спортсмен' if turn['role'] == 'user' else 'Ты'}: {turn['content']}"
            for turn in history
        )
        parts.append(f"Предыдущие реплики этого разговора:\n{rendered}")
    parts.append(f"Новый вопрос спортсмена:\n{question}")
    parts.append(f"Отвечай с опорой на его данные. Контекст:\n{render_context(context)}")

    text = llm.text("\n\n".join(parts), system=coach_system(),
                    effort=EFFORT_ANALYSIS, max_tokens=4000)
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
