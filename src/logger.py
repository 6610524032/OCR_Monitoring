import atexit
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional


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


DEFAULT_LOG_LEVEL = logging.INFO
FILE_RETRY_SECONDS = 30
MAX_LOG_RECORD_LENGTH = 50_000


_HANDLER_LOCK = threading.RLock()

_FILE_HANDLER: Optional[
    logging.Handler
] = None

_CONSOLE_HANDLER: Optional[
    logging.Handler
] = None


_SECRET_PATTERNS = (
    re.compile(
        (
            r"(?i)"
            r"(authorization\s*[:=]\s*"
            r"bearer\s+)"
            r"([^\s,;]+)"
        )
    ),
    re.compile(
        (
            r"(?i)"
            r"(rtsp://[^:/@\s]+:)"
            r"([^@\s]+)"
            r"(@)"
        )
    ),
    re.compile(
        (
            r"(?i)"
            r"("
            r"[\"']?"
            r"(?:"
            r"password"
            r"|camera_password"
            r"|api[_ -]?key"
            r"|apikey"
            r"|sensor_api_key"
            r"|access_token"
            r"|refresh_token"
            r"|token"
            r"|secret"
            r")"
            r"[\"']?"
            r"\s*[:=]\s*"
            r"[\"']?"
            r")"
            r"([^\"',}\s]+)"
        )
    ),
)


def _redact_sensitive_text(
    value,
) -> str:
    try:
        text = str(
            value
        )

    except Exception:
        text = (
            "[UNPRINTABLE LOG MESSAGE]"
        )

    text = _SECRET_PATTERNS[
        0
    ].sub(
        r"\1[REDACTED]",
        text,
    )

    text = _SECRET_PATTERNS[
        1
    ].sub(
        r"\1[REDACTED]\3",
        text,
    )

    text = _SECRET_PATTERNS[
        2
    ].sub(
        r"\1[REDACTED]",
        text,
    )

    if (
        len(
            text
        )
        > MAX_LOG_RECORD_LENGTH
    ):
        text = (
            text[
                :MAX_LOG_RECORD_LENGTH
            ]
            + " ... [LOG RECORD TRUNCATED]"
        )

    return text


def _write_fallback_message(
    message,
) -> None:
    """
    Write a minimal message directly to stderr.

    This function must never use logging because
    it is also used when the logging system fails.
    """
    try:
        safe_message = (
            _redact_sensitive_text(
                message
            )
        )

        sys.stderr.write(
            safe_message.rstrip(
                "\r\n"
            )
            + "\n"
        )

        sys.stderr.flush()

    except Exception:
        # Logging failure must not interrupt
        # Web, API, or Worker execution.
        return


def _resolve_log_level(
    environment_name: str,
    fallback_level: int,
) -> int:
    configured_value = os.getenv(
        environment_name,
        "",
    ).strip().upper()

    if not configured_value:
        return fallback_level

    resolved_level = getattr(
        logging,
        configured_value,
        None,
    )

    if not isinstance(
        resolved_level,
        int,
    ):
        _write_fallback_message(
            (
                "[LOGGER] Invalid "
                f"{environment_name}="
                f"{configured_value!r}; "
                "using the default level"
            )
        )

        return fallback_level

    return resolved_level


def _general_log_level() -> int:
    return _resolve_log_level(
        "LOG_LEVEL",
        DEFAULT_LOG_LEVEL,
    )


def _file_log_level() -> int:
    return _resolve_log_level(
        "LOG_FILE_LEVEL",
        _general_log_level(),
    )


def _console_log_level() -> int:
    return _resolve_log_level(
        "LOG_CONSOLE_LEVEL",
        _general_log_level(),
    )


class RedactingFormatter(
    logging.Formatter
):
    """
    Redact common credentials from the complete
    formatted record, including exception text.
    """

    def format(
        self,
        record,
    ) -> str:
        try:
            formatted = super().format(
                record
            )

        except Exception:
            formatted = (
                f"{record.levelname} | "
                f"{record.name} | "
                "[LOG FORMAT ERROR]"
            )

        return _redact_sensitive_text(
            formatted
        )


class ResilientFileHandler(
    logging.FileHandler
):
    """
    FileHandler that temporarily disables file writes
    after an error and retries later.

    Console logging continues while the log file is
    unavailable. No file rotation is performed because
    several Windows processes may hold the same file.
    """

    def __init__(
        self,
        filename,
        mode="a",
        encoding="utf-8",
        delay=True,
        errors="backslashreplace",
    ):
        super().__init__(
            filename=filename,
            mode=mode,
            encoding=encoding,
            delay=delay,
            errors=errors,
        )

        self._retry_after = 0.0
        self._emit_failed = False
        self._failure_reported = False

        self._ocr_clean_handler_role = (
            "file"
        )

    def _open(
        self,
    ):
        try:
            Path(
                self.baseFilename
            ).parent.mkdir(
                parents=True,
                exist_ok=True,
            )

        except OSError:
            # The normal FileHandler open call below
            # will fail and invoke handleError().
            pass

        return super()._open()

    def emit(
        self,
        record,
    ) -> None:
        current_time = (
            time.monotonic()
        )

        if (
            current_time
            < self._retry_after
        ):
            return

        self._emit_failed = False

        super().emit(
            record
        )

        if not self._emit_failed:
            self._retry_after = 0.0
            self._failure_reported = False

    def handleError(
        self,
        record,
    ) -> None:
        """
        Suppress logging I/O errors so they do not
        terminate application processing.
        """
        self._emit_failed = True

        self._retry_after = (
            time.monotonic()
            + FILE_RETRY_SECONDS
        )

        try:
            if self.stream is not None:
                self.stream.close()

        except Exception:
            pass

        finally:
            self.stream = None

        if self._failure_reported:
            return

        self._failure_reported = True

        try:
            record_message = (
                record.getMessage()
            )

        except Exception:
            record_message = (
                "[UNAVAILABLE LOG MESSAGE]"
            )

        _write_fallback_message(
            (
                "[LOGGER] Cannot write to "
                f"{self.baseFilename}. "
                f"File logging will retry in "
                f"{FILE_RETRY_SECONDS} seconds. "
                f"Original message: "
                f"{record_message}"
            )
        )


def _create_formatter(
) -> logging.Formatter:
    return RedactingFormatter(
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


def _create_console_handler(
    formatter,
) -> logging.Handler:
    handler = logging.StreamHandler(
        stream=sys.stderr
    )

    handler.setLevel(
        _console_log_level()
    )

    handler.setFormatter(
        formatter
    )

    handler._ocr_clean_handler_role = (
        "console"
    )

    return handler


def _create_file_handler(
    formatter,
) -> Optional[
    logging.Handler
]:
    try:
        # delay=True means the file is not opened
        # until the first record is emitted.
        handler = ResilientFileHandler(
            LOG_FILE_PATH,
            mode="a",
            encoding="utf-8",
            delay=True,
            errors="backslashreplace",
        )

        handler.setLevel(
            _file_log_level()
        )

        handler.setFormatter(
            formatter
        )

        return handler

    except Exception as error:
        _write_fallback_message(
            (
                "[LOGGER] Cannot create file "
                f"handler for {LOG_FILE_PATH}: "
                f"{type(error).__name__}: "
                f"{error}"
            )
        )

        return None


def _get_shared_handlers():
    """
    Create one file handler and one console handler
    per Python process.

    Python logging handlers already serialize writes
    between threads within the same process.
    """
    global _FILE_HANDLER
    global _CONSOLE_HANDLER

    with _HANDLER_LOCK:
        formatter = (
            _create_formatter()
        )

        if _CONSOLE_HANDLER is None:
            _CONSOLE_HANDLER = (
                _create_console_handler(
                    formatter
                )
            )

        if _FILE_HANDLER is None:
            _FILE_HANDLER = (
                _create_file_handler(
                    formatter
                )
            )

        return (
            _FILE_HANDLER,
            _CONSOLE_HANDLER,
        )


def _replace_project_handler(
    logger,
    handler,
    role: str,
) -> None:
    """
    Remove stale project handlers created by module
    reloads and attach the current shared handler.
    """
    for existing_handler in list(
        logger.handlers
    ):
        existing_role = getattr(
            existing_handler,
            "_ocr_clean_handler_role",
            None,
        )

        if existing_role != role:
            continue

        if existing_handler is handler:
            return

        logger.removeHandler(
            existing_handler
        )

        try:
            existing_handler.close()

        except Exception:
            pass

    if handler is not None:
        logger.addHandler(
            handler
        )


def create_logger(
    name: str,
) -> logging.Logger:
    """
    Create or return a project logger.

    Output:
    - Terminal through stderr
    - logs/app_log.txt when available
    """
    logger_name = str(
        name
        or "ocr_clean"
    ).strip()

    if not logger_name:
        logger_name = "ocr_clean"

    logger = logging.getLogger(
        logger_name
    )

    file_handler, console_handler = (
        _get_shared_handlers()
    )

    active_levels = [
        handler.level
        for handler in (
            file_handler,
            console_handler,
        )
        if handler is not None
    ]

    logger.setLevel(
        min(
            active_levels
        )
        if active_levels
        else DEFAULT_LOG_LEVEL
    )

    logger.propagate = False

    with _HANDLER_LOCK:
        _replace_project_handler(
            logger=logger,
            handler=file_handler,
            role="file",
        )

        _replace_project_handler(
            logger=logger,
            handler=console_handler,
            role="console",
        )

    return logger


def _close_shared_handlers(
) -> None:
    global _FILE_HANDLER
    global _CONSOLE_HANDLER

    with _HANDLER_LOCK:
        handlers = (
            _FILE_HANDLER,
            _CONSOLE_HANDLER,
        )

        _FILE_HANDLER = None
        _CONSOLE_HANDLER = None

        for handler in handlers:
            if handler is None:
                continue

            try:
                handler.flush()

            except Exception:
                pass

            try:
                handler.close()

            except Exception:
                pass


atexit.register(
    _close_shared_handlers
)