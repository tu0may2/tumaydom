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
    progress_report,
    today_session,
    weekly_review,
)
from .config import Settings, get_settings
from .db import Database
from .export import export_workbook
from .ingest.files import load_file
from .ingest.parser import apply_ingest, is_greeting, looks_like_question, parse_message
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
/progress — рост силовых и беговых по каждому упражнению
/export — выгрузка всей статистики в Excel
/forget — забыть контекст разговора (данные останутся)
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


class _Typing:
    """Держит статус «печатает» всё время, пока думает модель.

    Telegram гасит его через 5 секунд, а локальная модель отвечает минутами —
    без этого выглядит так, будто бот завис.
    """

    def __init__(self, update: Update) -> None:
        self._chat = update.effective_chat
        self._task: asyncio.Task | None = None

    async def _loop(self) -> None:
        while True:
            try:
                await self._chat.send_action(ChatAction.TYPING)
            except Exception:  # сеть моргнула — не повод падать
                pass
            await asyncio.sleep(4)

    async def __aenter__(self) -> "_Typing":
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._task:
            self._task.cancel()


def _explain(exc: Exception) -> str:
    """Перевод ошибки в понятную фразу с указанием, что чинить."""
    text = str(exc).lower()
    if "connect" in text or "refused" in text:
        return ("Модель не отвечает — похоже, Ollama не запущена. "
                "Проверь значок ламы в трее и запусти её.")
    if "timeout" in text or "timed out" in text:
        return ("Модель не успела ответить. Для локальной модели это бывает на "
                "длинных разборах — попробуй ещё раз или возьми модель полегче "
                "(FITCOACH_MODEL=gemma3:4b).")
    if "not found" in text and "model" in text:
        return "Модель не скачана — выполни в PowerShell: ollama pull gemma3:12b"
    if "json" in text:
        return ("Модель вернула ответ, который не удалось разобрать. "
                "Повтори запрос; если повторяется — нужна модель посильнее.")
    return f"Что-то пошло не так: {exc}"


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
    await _send(update, "Собираю разбор, это займёт до нескольких минут…")
    async with _Typing(update):
        try:
            text = await asyncio.to_thread(morning_digest, llm, db, update.effective_user.id)
        except Exception as exc:
            log.exception("Дайджест не собрался")
            await _send(update, _explain(exc))
            return
    await _send(update, text)


async def cmd_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Динамика силовых и кардио. Считается кодом, поэтому отвечает мгновенно."""
    db, _, _ = _deps(context)
    await _send(update, progress_report(db, update.effective_user.id))


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Собрать .xlsx со всей статистикой и прислать файлом."""
    db, llm, _ = _deps(context)
    user_id = update.effective_user.id

    if not db.recent_workouts(user_id, days=365) and not db.recent_sleep(user_id, days=365):
        await _send(update, "Выгружать нечего — сначала пришли хотя бы пару тренировок.")
        return

    await _send(update, "Собираю файл…")
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
    # Два запроса к модели с полной историей — на локальной это долго.
    await _send(update, "Разбираю неделю и собираю план. На локальной модели "
                        "это может занять 5–10 минут, я напишу, когда будет готово.")
    async with _Typing(update):
        try:
            review, _plan = await asyncio.to_thread(
                weekly_review, llm, db, update.effective_user.id
            )
        except Exception as exc:
            log.exception("Недельный разбор не собрался")
            await _send(update, _explain(exc))
            return
    await _send(update, review + "\n\nНовый план сохранён — посмотреть: /plan")


# --------------------------------------------------------------- сообщения


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, llm, _ = _deps(context)
    user_id = update.effective_user.id
    text = update.effective_message.text or ""
    db.update_profile(user_id, {}, chat_id=update.effective_chat.id)
    db.add_dialog(user_id, "user", text)

    # Приветствие не стоит прогона локальной модели — отвечаем сразу.
    if is_greeting(text):
        reply = _greeting_reply(db, user_id)
        db.add_dialog(user_id, "assistant", reply)
        await _send(update, reply)
        return

    async with _Typing(update):
        try:
            # Вопрос без цифр разбирать не нужно — экономим один запрос к модели,
            # а для локальной это половина времени ответа.
            if looks_like_question(text):
                answer = await asyncio.to_thread(answer_question, llm, db, user_id, text)
                db.add_dialog(user_id, "assistant", answer)
                await _send(update, answer)
                return

            parsed = await asyncio.to_thread(parse_message, llm, text=text)
        except Exception as exc:
            log.exception("Обработка текста не удалась")
            await _send(update, _explain(exc))
            return

        await _handle_parsed(update, db, llm, user_id, parsed, source="text", raw=text,
                             question=text)


def _greeting_reply(db: Database, user_id: int) -> str:
    """Мгновенный ответ на «привет» — с подсказкой, что делать дальше."""
    profile = db.get_profile(user_id)
    session = today_session(db, user_id)

    if not profile:
        return ("Привет. Расскажи о себе — возраст, рост, вес, цель, сколько дней "
                "в неделю тренируешься, какой инвентарь и есть ли ограничения. "
                "Дальше присылай тренировки: «жим 80x5x5 RPE 8» или «бег 8 км за 42 мин».")
    if session and session.get("kind") != "rest":
        return (f"Привет. Сегодня по плану: {session.get('title')}. "
                "Как отработаешь — пришли подходы, разберу и посчитаю прогресс.")
    if session:
        return "Привет. Сегодня по плану отдых. Если взвешивался — пришли вес."
    return ("Привет. Присылай тренировку («присед 100x5x5 RPE 8»), скриншот сна "
            "или вопрос. /progress покажет динамику, /digest — разбор на сегодня.")


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db, llm, _ = _deps(context)
    user_id = update.effective_user.id
    message = update.effective_message

    photo = message.photo[-1]  # самый большой размер
    telegram_file = await photo.get_file()
    blob = bytes(await telegram_file.download_as_bytearray())
    encoded = base64.standard_b64encode(blob).decode("utf-8")

    async with _Typing(update):
        try:
            parsed = await asyncio.to_thread(
                parse_message, llm, text=message.caption or "",
                images=[(encoded, "image/jpeg")]
            )
        except ValueError as exc:  # провайдер без vision
            await _send(update, str(exc))
            return
        except Exception as exc:
            log.exception("Разбор фото не удался")
            await _send(update, _explain(exc))
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

    async with _Typing(update):
        try:
            result = await asyncio.to_thread(load_file, document.file_name or "", blob)
        except ValueError as exc:
            await _send(update, str(exc))
            return

        try:
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
        except Exception as exc:
            log.exception("Разбор файла не удался")
            await _send(update, _explain(exc))
            return

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
        db.add_dialog(user_id, "assistant", text)
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
        db.add_dialog(user_id, "assistant", text)
        await _send(update, text)
        return

    await _send(update, parsed.get("comment") or "Не понял, что это. Опиши словами.")


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Видео, кружки, голосовые: разбирать их бот не умеет."""
    await _send(
        update,
        "Видео и голосовые я не разбираю — оценить технику по ролику не смогу. "
        "Опиши подход текстом («присед 100x5, колени сводит на третьем повторе»), "
        "или пришли скриншот статистики из Garmin.",
    )


async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Забыть контекст разговора, но не данные тренировок."""
    db, _, _ = _deps(context)
    db.clear_dialog(update.effective_user.id)
    await _send(update, "Забыл, о чём мы говорили. Тренировки, сон и замеры на месте.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Ошибка при обработке апдейта", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            _explain(context.error) if isinstance(context.error, Exception)
            else "Что-то пошло не так при обработке. Попробуй ещё раз."
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
    application.add_handler(CommandHandler("progress", cmd_progress))
    application.add_handler(CommandHandler("export", cmd_export))
    application.add_handler(CommandHandler("forget", cmd_forget))
    application.add_handler(MessageHandler(filters.PHOTO, on_photo))
    application.add_handler(MessageHandler(
        filters.VIDEO | filters.VIDEO_NOTE | filters.VOICE | filters.AUDIO, on_media))
    application.add_handler(MessageHandler(filters.Document.ALL, on_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_error_handler(on_error)
    application.post_init = _warm_up

    return application


async def _warm_up(application: Application) -> None:
    """Разбудить модель на старте, чтобы первый ответ не ждал загрузки весов."""
    llm = application.bot_data["llm"]

    async def run() -> None:
        try:
            await asyncio.to_thread(
                llm.text, "ок", system="Отвечай одним словом.", max_tokens=8
            )
            log.info("Модель %s прогрета и готова", llm.model)
        except Exception as exc:
            log.warning("Прогрев модели не удался (%s) — проверь: python -m fitcoach.doctor",
                        exc)

    asyncio.create_task(run())
