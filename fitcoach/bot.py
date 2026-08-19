"""Telegram-бот: приём данных, разбор, дайджесты."""

from __future__ import annotations

import asyncio
import base64
import logging
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .analysis.coach import (
    analyze_workout,
    answer_question,
    morning_digest,
    today_session,
    weekly_review,
)
from .config import Settings, get_settings
from .db import Database
from .export import export_workbook
from .ingest.files import load_file
from .ingest.parser import apply_ingest, parse_message
from .llm import LLM

log = logging.getLogger(__name__)

MAX_TELEGRAM_CHARS = 4000
MAX_FILE_BYTES = 5 * 1024 * 1024

HELP = """Я веду твои тренировки, сон и питание.

Просто пиши, что сделал: «жим 80x5x5, RPE 8» или «бег 10 км за 52 мин, пульс 148».
Скидывай скриншоты из Garmin Connect — разберу сон и активности.
Файлы выгрузки CSV/JSON тоже принимаю.
Вопросы про питание, технику и план — тоже сюда.

Команды:
/today — что сегодня по плану
/plan — план на неделю
/digest — прислать утренний разбор прямо сейчас
/week — недельный разбор и новый план
/export — выгрузка всей статистики в Excel
/profile — показать профиль (цель, антропометрия, ограничения)
/whoami — мой chat_id
"""


# --------------------------------------------------------------- инфраструктура


def _deps(context: ContextTypes.DEFAULT_TYPE) -> tuple[Database, LLM, Settings]:
    data = context.application.bot_data
    return data["db"], data["llm"], data["settings"]


async def _send(update: Update, text: str) -> None:
    """Отправка с разбиением на куски по лимиту Telegram."""
    for chunk in _chunks(text, MAX_TELEGRAM_CHARS):
        await update.effective_message.reply_text(chunk)


def _chunks(text: str, size: int) -> list[str]:
    """Режем по абзацам; абзац длиннее лимита — жёстко по символам."""
    if len(text) <= size:
        return [text]

    parts: list[str] = []
    current = ""
    for paragraph in text.split("\n"):
        while len(paragraph) > size:
            if current.strip():
                parts.append(current.rstrip())
                current = ""
            parts.append(paragraph[:size])
            paragraph = paragraph[size:]
        if len(current) + len(paragraph) + 1 > size and current.strip():
            parts.append(current.rstrip())
            current = ""
        current += paragraph + "\n"
    if current.strip():
        parts.append(current.rstrip())
    return parts


# ----------------------------------------------------------------- команды


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, _, _ = _deps(context)
    db.update_profile(update.effective_user.id, {}, chat_id=update.effective_chat.id)
    await _send(update, HELP)


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send(update, f"chat_id: {update.effective_chat.id}\nuser_id: {update.effective_user.id}")


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, _, _ = _deps(context)
    profile = db.get_profile(update.effective_user.id)
    if not profile:
        await _send(update, "Профиль пуст. Напиши о себе: возраст, рост, вес, цель, "
                            "сколько дней в неделю тренируешься, инвентарь, ограничения.")
        return
    lines = [f"{key}: {value}" for key, value in profile.items()]
    await _send(update, "Профиль:\n" + "\n".join(lines))


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, _, _ = _deps(context)
    session = today_session(db, update.effective_user.id)
    if not session:
        await _send(update, "На сегодня в плане ничего нет. /week соберёт новый план.")
        return
    blocks = "\n".join(f"— {block}" for block in session.get("blocks") or [])
    rpe = session.get("target_rpe")
    await _send(
        update,
        f"Сегодня: {session.get('title')} ({session.get('kind')})\n{blocks}"
        + (f"\nЦелевое RPE: {rpe}" if rpe else ""),
    )


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, _, _ = _deps(context)
    plan = db.get_plan(update.effective_user.id)
    if not plan:
        await _send(update, "Плана пока нет. /week соберёт его по твоим данным.")
        return
    lines = [f"Неделя с {plan['week_start']} — {plan.get('focus', '')}".strip()]
    for day in plan.get("days") or []:
        lines.append(f"\n{day['weekday']}: {day.get('title')} ({day.get('kind')})")
        lines += [f"  — {block}" for block in day.get("blocks") or []]
    nutrition = plan.get("nutrition") or {}
    if nutrition.get("kcal"):
        lines.append(
            f"\nПитание: {nutrition['kcal']:.0f} ккал, Б {nutrition.get('protein_g', 0):.0f} / "
            f"Ж {nutrition.get('fat_g', 0):.0f} / У {nutrition.get('carbs_g', 0):.0f}"
        )
    await _send(update, "\n".join(lines))


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, llm, _ = _deps(context)
    await update.effective_chat.send_action(ChatAction.TYPING)
    text = await asyncio.to_thread(morning_digest, llm, db, update.effective_user.id)
    await _send(update, text)


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Собрать .xlsx со всей статистикой и прислать файлом."""
    db, llm, _ = _deps(context)
    user_id = update.effective_user.id

    if not db.recent_workouts(user_id, days=365) and not db.recent_sleep(user_id, days=365):
        await _send(update, "Выгружать нечего — сначала пришли хотя бы пару тренировок.")
        return

    await update.effective_chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"fitcoach-{date.today().isoformat()}.xlsx"
        await asyncio.to_thread(export_workbook, db, user_id, path, llm=llm)
        with path.open("rb") as handle:
            await update.effective_message.reply_document(
                document=handle,
                filename=path.name,
                caption="Листы: Обзор, Разбор, Недели, Прогресс, Тренировки, Сон, Замеры.",
            )


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, llm, _ = _deps(context)
    await update.effective_chat.send_action(ChatAction.TYPING)
    review, _plan = await asyncio.to_thread(weekly_review, llm, db, update.effective_user.id)
    await _send(update, review + "\n\nНовый план сохранён — посмотреть: /plan")


# --------------------------------------------------------------- сообщения


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, llm, _ = _deps(context)
    user_id = update.effective_user.id
    text = update.effective_message.text or ""
    db.update_profile(user_id, {}, chat_id=update.effective_chat.id)

    await update.effective_chat.send_action(ChatAction.TYPING)
    parsed = await asyncio.to_thread(parse_message, llm, text=text)
    await _handle_parsed(update, db, llm, user_id, parsed, source="text", raw=text,
                         question=text)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, llm, _ = _deps(context)
    user_id = update.effective_user.id
    message = update.effective_message

    photo = message.photo[-1]  # самый большой размер
    telegram_file = await photo.get_file()
    blob = bytes(await telegram_file.download_as_bytearray())
    encoded = base64.standard_b64encode(blob).decode("utf-8")

    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        parsed = await asyncio.to_thread(
            parse_message, llm, text=message.caption or "", images=[(encoded, "image/jpeg")]
        )
    except ValueError as exc:  # провайдер без vision
        await _send(update, str(exc))
        return
    await _handle_parsed(update, db, llm, user_id, parsed, source="photo",
                         raw=message.caption, question=message.caption)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, llm, _ = _deps(context)
    user_id = update.effective_user.id
    document = update.effective_message.document

    if document.file_size and document.file_size > MAX_FILE_BYTES:
        await _send(update, "Файл больше 5 МБ — пришли выгрузку поменьше или за меньший период.")
        return

    telegram_file = await document.get_file()
    blob = bytes(await telegram_file.download_as_bytearray())

    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        result = await asyncio.to_thread(load_file, document.file_name or "", blob)
    except ValueError as exc:
        await _send(update, str(exc))
        return

    if result["text"]:  # формат не распознали — отдаём модели как текст
        parsed = await asyncio.to_thread(parse_message, llm, text=result["text"])
    else:
        parsed = {
            "intent": "workout" if result["workouts"] else "sleep",
            "workouts": result["workouts"],
            "sleep": result["sleep"],
            "metrics": [],
            "profile_patch": {},
            "comment": "",
        }

    await _handle_parsed(update, db, llm, user_id, parsed, source="file",
                         raw=document.file_name)


async def _handle_parsed(
    update: Update,
    db: Database,
    llm: LLM,
    user_id: int,
    parsed: dict[str, Any],
    *,
    source: str,
    raw: str | None,
    question: str | None = None,
) -> None:
    counts = apply_ingest(db, user_id, parsed, source=source, raw=raw)

    if counts["workouts"]:
        workout = (parsed.get("workouts") or [])[-1]
        text = await asyncio.to_thread(analyze_workout, llm, db, user_id, workout)
        await _send(update, text)
        return

    if counts["sleep"] or counts["metrics"] or counts["profile"]:
        saved = []
        if counts["sleep"]:
            saved.append(f"сон ×{counts['sleep']}")
        if counts["metrics"]:
            saved.append(f"показатели ×{counts['metrics']}")
        if counts["profile"]:
            saved.append("профиль")
        await _send(update, "Записал: " + ", ".join(saved) + ". Учту в утреннем разборе.")
        return

    if question:
        text = await asyncio.to_thread(answer_question, llm, db, user_id, question)
        await _send(update, text)
        return

    await _send(update, parsed.get("comment") or "Не понял, что это. Опиши словами.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Ошибка при обработке апдейта", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "Что-то пошло не так при обработке. Попробуй ещё раз или пришли данные текстом."
        )


def build_application(settings: Settings | None = None) -> Application:
    settings = settings or get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан — заполни .env")

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data.update(
        {"db": Database(settings.db_path), "llm": LLM(), "settings": settings}
    )

    application.add_handler(CommandHandler(["start", "help"], cmd_start))
    application.add_handler(CommandHandler("whoami", cmd_whoami))
    application.add_handler(CommandHandler("profile", cmd_profile))
    application.add_handler(CommandHandler("today", cmd_today))
    application.add_handler(CommandHandler("plan", cmd_plan))
    application.add_handler(CommandHandler("digest", cmd_digest))
    application.add_handler(CommandHandler("week", cmd_week))
    application.add_handler(CommandHandler("export", cmd_export))
    application.add_handler(MessageHandler(filters.PHOTO, on_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, on_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_error_handler(on_error)

    return application
