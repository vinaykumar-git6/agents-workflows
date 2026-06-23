"""Central logging configuration for the AWB OCR worker.

Configures both console and rotating file handlers. All application logs are
written to ``app.log`` at the project root with timestamps, logger name, level,
and message. Call :func:`setup_logging` once at process startup (before any
significant work) to take effect.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# app.log lives at the worker project root (parent of the `app` package).
# Override with LOG_FILE env var; set to empty to disable file logging entirely
# (e.g. in containers running as a non-root user with a read-only app dir).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = Path(os.getenv("LOG_FILE", str(_PROJECT_ROOT / "app.log")))

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging() -> None:
    """Configure root logging with console + rotating file handlers.

    Idempotent: safe to call multiple times (only configures once).
    """
    global _configured
    if _configured:
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    root = logging.getLogger()
    root.setLevel(level)

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file handler -> app.log (5 MB x 5 backups). Skip gracefully if the
    # target directory is not writable (e.g. non-root container, read-only fs).
    file_logging = False
    if str(LOG_FILE):
        try:
            file_handler = RotatingFileHandler(
                LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
            file_logging = True
        except OSError as exc:
            root.warning("File logging disabled (%s): %s", LOG_FILE, exc)

    # Quiet noisy third-party loggers but keep them in the file at WARNING.
    for noisy in ("azure", "azure.identity", "azure.core.pipeline", "urllib3", "httpx", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
    if file_logging:
        logging.getLogger("awb.logging").info("Logging configured. Writing to %s", LOG_FILE)
    else:
        logging.getLogger("awb.logging").info("Logging configured (console only).")
