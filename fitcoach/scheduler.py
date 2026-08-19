"""Расписание: утренний дайджест и недельный разбор через JobQueue бота."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from telegram.ext import Application, ContextTypes

from datetime import date

from .analysis.coach import morning_digest, today_session, weekly_review
from .config import Settings

log = logging.getLogger(__name__)

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


async def _morning_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    db, llm = context.application.bot_data["db"], context.application.bot_data["llm"]
    for user_id, chat_id in db.subscribers():
        try:
            text = await asyncio.to_thread(morning_digest, llm, db, user_id)
            await context.bot.send_message(chat_id=chat_id, text=text[:4000])
        except Exception:  # один упавший пользователь не должен ронять рассылку
            log.exception("Утренний дайджест не отправлен: user_id=%s", user_id)


def _nudge_text(session: dict | None) -> str:
    """Текст напоминания зависит от того, что стояло в плане."""
    if session and session.get("kind") == "rest":
        return ("Сегодня по плану отдых — отчёта не жду. Если всё же что-то делал, "
                "напиши. И пришли вес, если взвешивался.")
    if session:
        blocks = "; ".join(session.get("blocks") or [])
        return (f"Сегодня в плане было: {session.get('title')}"
                + (f" ({blocks})" if blocks else "")
                + ". Тренировался? Пришли подходы — разберу и посчитаю прогресс. "
                  "Если пропустил, тоже напиши, учту в плане.")
    return ("Ты сегодня тренировался? Пришли, что делал — например "
            "«жим 80x5x5 RPE 8» или «бег 8 км за 42 мин». "
            "Если день был без тренировки, так и скажи.")


async def _evening_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Вечернее напоминание тем, кто сегодня не отчитался о тренировке."""
    db = context.application.bot_data["db"]
    today = date.today().isoformat()

    for user_id, chat_id in db.subscribers():
        try:
            if db.workouts_on(user_id, today) or db.sent_today(user_id, "nudge"):
                continue
            text = _nudge_text(today_session(db, user_id))
            await context.bot.send_message(chat_id=chat_id, text=text)
            db.log_message(user_id, "nudge", text)
        except Exception:
            log.exception("Напоминание не отправлено: user_id=%s", user_id)


async def _weekly_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    db, llm = context.application.bot_data["db"], context.application.bot_data["llm"]
    for user_id, chat_id in db.subscribers():
        try:
            review, _plan = await asyncio.to_thread(weekly_review, llm, db, user_id)
            await context.bot.send_message(
                chat_id=chat_id,
                text=(review + "\n\nПлан на следующую неделю готов: /plan")[:4000],
            )
        except Exception:
            log.exception("Недельный разбор не отправлен: user_id=%s", user_id)


def schedule_jobs(application: Application, settings: Settings) -> None:
    job_queue = application.job_queue
    if job_queue is None:
        raise RuntimeError(
            "JobQueue недоступен — установи python-telegram-bot с extra [job-queue]"
        )

    tzinfo = ZoneInfo(settings.timezone)

    morning_h, morning_m = settings.hhmm(settings.morning_time)
    job_queue.run_daily(
        _morning_job,
        time=dt.time(hour=morning_h, minute=morning_m, tzinfo=tzinfo),
        name="morning_digest",
    )

    evening_h, evening_m = settings.hhmm(settings.evening_time)
    job_queue.run_daily(
        _evening_job,
        time=dt.time(hour=evening_h, minute=evening_m, tzinfo=tzinfo),
        name="evening_nudge",
    )

    weekly_h, weekly_m = settings.hhmm(settings.weekly_time)
    weekday = WEEKDAYS.get(settings.weekly_day.lower()[:3], 6)
    job_queue.run_daily(
        _weekly_job,
        time=dt.time(hour=weekly_h, minute=weekly_m, tzinfo=tzinfo),
        days=(weekday,),
        name="weekly_review",
    )

    log.info(
        "Расписание: дайджест в %s, напоминание в %s, недельный разбор в %s %s (%s)",
        settings.morning_time, settings.evening_time, settings.weekly_day,
        settings.weekly_time, settings.timezone,
    )
