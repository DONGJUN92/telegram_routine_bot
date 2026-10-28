"""Shared console and local-file logging for the bot runtime."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


_CONFIGURED = False


def _configure_console_encoding(stream):
    """Avoid Windows legacy encodings turning an emoji log into a crash."""
    try:
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, OSError):
        pass


def configure_logging():
    """Keep runtime diagnostics visible in the console and on local disk."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = os.environ.get("BOT_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    _configure_console_encoding(sys.stdout)
    _configure_console_encoding(sys.stderr)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    log_directory = Path(os.environ.get("BOT_LOG_DIR", "logs"))
    try:
        log_directory.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_directory / "routine_bot.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except OSError as error:
        print(f"Unable to create local log file: {error}", file=sys.stderr)

    logging.captureWarnings(True)
    # httpx includes full request URLs in INFO logs. Telegram URLs embed the
    # bot token, so keep transport diagnostics at warning level or higher.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _CONFIGURED = True
