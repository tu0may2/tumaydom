"""Точка входа: запуск Telegram-бота с расписанием."""

from __future__ import annotations

import logging

from dotenv import load_dotenv

from fitcoach.bot import build_application
from fitcoach.config import get_settings
from fitcoach.scheduler import schedule_jobs


def main() -> None:
    load_dotenv()
    # Пишем и в консоль, и в файл: окно PowerShell прокручивается, а разбираться
    # с ошибкой обычно приходится позже.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("fitcoach.log", encoding="utf-8"),
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = get_settings()
    application = build_application(settings)
    schedule_jobs(application, settings)
    application.run_polling()


if __name__ == "__main__":
    main()
