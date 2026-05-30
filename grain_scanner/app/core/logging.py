from __future__ import annotations

import sys

from loguru import logger

from app.core.config import settings


def setup_logging() -> None:
    """Configure loguru for stderr + rotating file output."""
    logger.remove()

    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stderr,
        format=fmt,
        level="DEBUG" if settings.debug else "INFO",
        colorize=True,
        enqueue=True,
    )

    logger.add(
        "logs/grain_scanner_{time:YYYY-MM-DD}.log",
        format=fmt,
        level="INFO",
        rotation="00:00",
        retention="30 days",
        compression="gz",
        enqueue=True,
    )
