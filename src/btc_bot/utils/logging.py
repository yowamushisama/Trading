"""Structured logging via loguru. Call setup_logging() once at process start."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logging(log_level: str = "INFO", log_file: str = "logs/bot.log") -> None:
    logger.remove()

    logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>"
        ),
        colorize=True,
    )

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_path,
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} — {message}",
        rotation="50 MB",
        retention=30,
        compression="gz",
        serialize=False,
    )
