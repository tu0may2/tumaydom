"""Расписание: утренний дайджест и недельный разбор через JobQueue бота."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from telegram.ext import Application, ContextTypes

from .analysis.coach import morning_digest, weekly_review
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

    weekly_h, weekly_m = settings.hhmm(settings.weekly_time)
    weekday = WEEKDAYS.get(settings.weekly_day.lower()[:3], 6)
    job_queue.run_daily(
        _weekly_job,
        time=dt.time(hour=weekly_h, minute=weekly_m, tzinfo=tzinfo),
        days=(weekday,),
        name="weekly_review",
    )

    log.info(
        "Расписание: дайджест ежедневно в %s, недельный разбор в %s %s (%s)",
        settings.morning_time, settings.weekly_day, settings.weekly_time, settings.timezone,
    )
