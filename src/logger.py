import logging
import threading
from pathlib import Path


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

LOGS_DIR = (
    PROJECT_ROOT
    / "logs"
)

LOG_FILE_PATH = (
    LOGS_DIR
    / "app_log.txt"
)

LOGS_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


_HANDLER_LOCK = threading.Lock()

_FILE_HANDLER = None
_CONSOLE_HANDLER = None


def _create_formatter():
    return logging.Formatter(
        (
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
        datefmt=(
            "%Y-%m-%d %H:%M:%S"
        ),
    )


def _get_shared_handlers():
    """
    Create one shared file handler and one shared
    console handler per Python process.

    File rotation is intentionally not performed here
    because API, Web, and Worker may keep app_log.txt
    open at the same time. On Windows, renaming an open
    file causes WinError 32.
    """
    global _FILE_HANDLER
    global _CONSOLE_HANDLER

    with _HANDLER_LOCK:
        formatter = _create_formatter()

        if _FILE_HANDLER is None:
            _FILE_HANDLER = logging.FileHandler(
                LOG_FILE_PATH,
                mode="a",
                encoding="utf-8",
                delay=False,
                errors="backslashreplace",
            )

            _FILE_HANDLER.setLevel(
                logging.INFO
            )

            _FILE_HANDLER.setFormatter(
                formatter
            )

        if _CONSOLE_HANDLER is None:
            _CONSOLE_HANDLER = (
                logging.StreamHandler()
            )

            _CONSOLE_HANDLER.setLevel(
                logging.INFO
            )

            _CONSOLE_HANDLER.setFormatter(
                formatter
            )

        return (
            _FILE_HANDLER,
            _CONSOLE_HANDLER,
        )


def create_logger(
    name: str,
) -> logging.Logger:
    """
    Create or return a project logger.

    Log output:
    - Terminal
    - logs/app_log.txt
    """
    logger = logging.getLogger(
        name
    )

    logger.setLevel(
        logging.INFO
    )

    logger.propagate = False

    file_handler, console_handler = (
        _get_shared_handlers()
    )

    if file_handler not in logger.handlers:
        logger.addHandler(
            file_handler
        )

    if console_handler not in logger.handlers:
        logger.addHandler(
            console_handler
        )

    return logger