"""Точка входа: запуск Telegram-бота с расписанием."""

from __future__ import annotations

import logging

from dotenv import load_dotenv

from telegram.error import NetworkError, TimedOut

from fitcoach.bot import build_application
from fitcoach.config import get_settings
from fitcoach.scheduler import schedule_jobs

NETWORK_HINT = """
Не удалось связаться с Telegram (api.telegram.org).

Обычные причины:
  1. Telegram заблокирован провайдером — включи VPN и запусти снова.
  2. Либо пропиши прокси только для Telegram в файле .env:
         FITCOACH_TELEGRAM_PROXY=socks5://127.0.0.1:1080
     (модель при этом останется локальной и через прокси не пойдёт)
  3. Нет интернета или его режет фаервол/антивирус.

Токен здесь ни при чём: до проверки токена дело не дошло.
"""


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

    try:
        application.run_polling()
    except (TimedOut, NetworkError):
        print(NETWORK_HINT)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
