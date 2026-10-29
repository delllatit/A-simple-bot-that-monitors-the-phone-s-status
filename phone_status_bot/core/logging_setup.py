"""إعداد نظام السجلات (ملف دوّار + وحدة تحكم)."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from phone_status_bot.core import config

logger = logging.getLogger("telegram_bot")

_configured = False


def setup_logging():
    """تهيئة السجلات مرة واحدة فقط (idempotent)."""
    global _configured
    if _configured:
        return logger

    log_dir = Path(config.LOG_FILE).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.WARNING)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    _configured = True
    return logger
