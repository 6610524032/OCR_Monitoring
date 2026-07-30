"""
Thread-safe OCR model status management.

The current state is kept in memory and persisted as an
atomic JSON file so Web, API, Worker, and preload processes
can inspect the model preparation status.
"""

import json
import os
import re
import tempfile
import threading
import time

from collections.abc import Mapping
from dataclasses import (
    asdict,
    dataclass,
)
from datetime import (
    datetime,
    timezone,
)
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Optional,
)

from src.logger import create_logger
from src.server.config import (
    MODEL_CACHE_DIR,
    OCR_ENGINE as DEFAULT_OCR_ENGINE,
)


logger = create_logger(
    "processing.ocr.model_status"
)


MAX_ENGINE_LENGTH = 100
MAX_MESSAGE_LENGTH = 500
MAX_ERROR_LENGTH = 2_000
MAX_STATUS_FILE_BYTES = 64 * 1024

STATUS_READ_ATTEMPTS = 2
STATUS_READ_RETRY_SECONDS = 0.05


_CONTROL_CHARACTER_PATTERN = re.compile(
    r"[\x00-\x1f\x7f]"
)


class OCRModelStatus(
    str,
    Enum,
):
    NOT_STARTED = "not_started"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"


@dataclass(
    frozen=True
)
class OCRModelState:
    engine: str
    status: OCRModelStatus
    message: str
    error: str
    updated_at: str


_MODEL_STATE_LOCK = (
    threading.RLock()
)


def _utc_now_iso() -> str:
    return (
        datetime.now(
            timezone.utc
        ).isoformat(
            timespec="microseconds"
        )
    )


def _clean_text(
    value: Any,
    max_length: int,
) -> str:
    if value is None:
        return ""

    try:
        text = str(
            value
        )

    except Exception:
        return ""

    text = _CONTROL_CHARACTER_PATTERN.sub(
        " ",
        text,
    )

    text = " ".join(
        text.split()
    )

    return text[
        :max_length
    ]


def _normalize_engine(
    value: Any,
) -> str:
    if isinstance(
        value,
        bool,
    ):
        normalized = ""

    else:
        normalized = _clean_text(
            value,
            MAX_ENGINE_LENGTH,
        ).casefold()

    if not normalized:
        raise ValueError(
            (
                "OCR engine name cannot "
                "be empty"
            )
        )

    return normalized


def _configured_engine() -> str:
    default_engine = (
        str(
            DEFAULT_OCR_ENGINE
        )
        if DEFAULT_OCR_ENGINE
        is not None
        else "trocr"
    )

    raw_engine = os.getenv(
        "OCR_ENGINE",
        default_engine,
    )

    try:
        return _normalize_engine(
            raw_engine
        )

    except ValueError:
        logger.warning(
            (
                "OCR_ENGINE is empty or "
                "invalid; using trocr"
            )
        )

        return "trocr"


def _coerce_status(
    value: Any,
) -> OCRModelStatus:
    if isinstance(
        value,
        OCRModelStatus,
    ):
        return value

    try:
        normalized = str(
            value
        ).strip().casefold()

        return OCRModelStatus(
            normalized
        )

    except (
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            (
                "Invalid OCR model status: "
                f"{value!r}"
            )
        ) from error


def _normalize_timestamp(
    value: Any,
) -> str:
    timestamp_text = _clean_text(
        value,
        100,
    )

    if not timestamp_text:
        raise ValueError(
            (
                "OCR status timestamp "
                "is missing"
            )
        )

    parse_text = timestamp_text

    if parse_text.endswith(
        "Z"
    ):
        parse_text = (
            parse_text[:-1]
            + "+00:00"
        )

    try:
        parsed = datetime.fromisoformat(
            parse_text
        )

    except ValueError as error:
        raise ValueError(
            (
                "OCR status timestamp "
                "is invalid"
            )
        ) from error

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(
        timezone.utc
    ).isoformat(
        timespec="microseconds"
    )


def _copy_state(
    state: OCRModelState,
) -> OCRModelState:
    return OCRModelState(
        engine=state.engine,
        status=state.status,
        message=state.message,
        error=state.error,
        updated_at=state.updated_at,
    )


def get_model_cache_dir() -> Path:
    configured_path = os.getenv(
        "MODEL_CACHE_DIR",
        "",
    ).strip()

    if configured_path:
        return Path(
            configured_path
        ).expanduser()

    return Path(
        MODEL_CACHE_DIR
    ).expanduser()


def get_status_file_path() -> Path:
    return (
        get_model_cache_dir()
        / "ocr_status.json"
    )


def _state_to_dict(
    state: OCRModelState,
) -> dict[str, str]:
    data = asdict(
        state
    )

    data["status"] = (
        state.status.value
    )

    return data


def _payload_to_state(
    payload: Any,
) -> OCRModelState:
    if not isinstance(
        payload,
        Mapping,
    ):
        raise ValueError(
            (
                "OCR status file must "
                "contain a JSON object"
            )
        )

    engine = _normalize_engine(
        payload.get(
            "engine"
        )
    )

    status = _coerce_status(
        payload.get(
            "status"
        )
    )

    message = _clean_text(
        payload.get(
            "message",
            "",
        ),
        MAX_MESSAGE_LENGTH,
    )

    error = _clean_text(
        payload.get(
            "error",
            "",
        ),
        MAX_ERROR_LENGTH,
    )

    updated_at = _normalize_timestamp(
        payload.get(
            "updated_at"
        )
    )

    return OCRModelState(
        engine=engine,
        status=status,
        message=message,
        error=error,
        updated_at=updated_at,
    )


def _write_state_file(
    state: OCRModelState,
) -> None:
    """
    Write the status through a unique temporary file
    and atomically replace the public JSON file.
    """
    status_file = (
        get_status_file_path()
    )

    status_directory = (
        status_file.parent
    )

    status_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload_text = json.dumps(
        _state_to_dict(
            state
        ),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"

    file_descriptor = None
    temporary_path = None

    try:
        (
            file_descriptor,
            temporary_name,
        ) = tempfile.mkstemp(
            prefix=".ocr_status_",
            suffix=".tmp",
            dir=str(
                status_directory
            ),
            text=True,
        )

        temporary_path = Path(
            temporary_name
        )

        with os.fdopen(
            file_descriptor,
            mode="w",
            encoding="utf-8",
            newline="\n",
        ) as temporary_file:
            file_descriptor = None

            temporary_file.write(
                payload_text
            )

            temporary_file.flush()

            os.fsync(
                temporary_file.fileno()
            )

        os.replace(
            temporary_path,
            status_file,
        )

        temporary_path = None

    finally:
        if file_descriptor is not None:
            try:
                os.close(
                    file_descriptor
                )

            except OSError:
                logger.debug(
                    (
                        "Cannot close OCR "
                        "status temporary file"
                    )
                )

        if temporary_path is not None:
            try:
                if temporary_path.exists():
                    temporary_path.unlink()

            except OSError:
                logger.debug(
                    (
                        "Cannot remove OCR "
                        "status temporary file: %s"
                    ),
                    temporary_path,
                )


def get_model_state() -> OCRModelState:
    with _MODEL_STATE_LOCK:
        return _copy_state(
            _MODEL_STATE
        )


def set_model_status(
    status: OCRModelStatus,
    message: str = "",
    error: str = "",
    engine: Optional[str] = None,
) -> OCRModelState:
    """
    Update the in-memory model status and persist it.

    Failure to write the status file does not discard the
    valid in-memory state or interrupt model preparation.
    """
    global _MODEL_STATE

    resolved_status = (
        _coerce_status(
            status
        )
    )

    clean_message = _clean_text(
        message,
        MAX_MESSAGE_LENGTH,
    )

    clean_error = _clean_text(
        error,
        MAX_ERROR_LENGTH,
    )

    with _MODEL_STATE_LOCK:
        if engine not in (
            None,
            "",
        ):
            resolved_engine = (
                _normalize_engine(
                    engine
                )
            )

        elif _MODEL_STATE.engine:
            resolved_engine = (
                _MODEL_STATE.engine
            )

        else:
            resolved_engine = (
                _configured_engine()
            )

        new_state = OCRModelState(
            engine=resolved_engine,
            status=resolved_status,
            message=clean_message,
            error=clean_error,
            updated_at=_utc_now_iso(),
        )

        _MODEL_STATE = new_state

        try:
            _write_state_file(
                new_state
            )

        except (
            OSError,
            TypeError,
            ValueError,
        ) as write_error:
            logger.warning(
                (
                    "Cannot persist OCR model "
                    "status file: %s"
                ),
                write_error,
            )

        state_copy = _copy_state(
            new_state
        )

    if (
        resolved_status
        == OCRModelStatus.READY
    ):
        logger.info(
            (
                "OCR model status changed: "
                "engine=%s, status=%s"
            ),
            state_copy.engine,
            state_copy.status.value,
        )

    elif (
        resolved_status
        == OCRModelStatus.ERROR
    ):
        logger.error(
            (
                "OCR model status changed: "
                "engine=%s, status=%s, "
                "message=%s"
            ),
            state_copy.engine,
            state_copy.status.value,
            state_copy.message,
        )

    else:
        logger.debug(
            (
                "OCR model status changed: "
                "engine=%s, status=%s"
            ),
            state_copy.engine,
            state_copy.status.value,
        )

    return state_copy


def _status_read_error_state(
    read_error: BaseException,
) -> dict[str, str]:
    error_text = _clean_text(
        read_error,
        MAX_ERROR_LENGTH,
    )

    return _state_to_dict(
        OCRModelState(
            engine=_configured_engine(),
            status=OCRModelStatus.ERROR,
            message=(
                "Cannot read OCR model status"
            ),
            error=error_text,
            updated_at=_utc_now_iso(),
        )
    )


def read_model_status_file() -> dict[str, str]:
    """
    Read and validate the persisted model status.

    The in-memory state is returned when the file does not
    exist. A malformed or inaccessible file produces a
    structured ERROR state rather than raising to the caller.
    """
    status_file = (
        get_status_file_path()
    )

    last_error = None

    for attempt in range(
        STATUS_READ_ATTEMPTS
    ):
        try:
            file_stat = (
                status_file.stat()
            )

            if (
                file_stat.st_size
                > MAX_STATUS_FILE_BYTES
            ):
                raise ValueError(
                    (
                        "OCR status file "
                        "is too large"
                    )
                )

            file_text = status_file.read_text(
                encoding="utf-8"
            )

            payload = json.loads(
                file_text
            )

            state = _payload_to_state(
                payload
            )

            return _state_to_dict(
                state
            )

        except FileNotFoundError:
            return _state_to_dict(
                get_model_state()
            )

        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as read_error:
            last_error = read_error

            if (
                attempt
                < STATUS_READ_ATTEMPTS - 1
            ):
                time.sleep(
                    STATUS_READ_RETRY_SECONDS
                )

    logger.warning(
        (
            "Cannot read OCR model "
            "status file: %s"
        ),
        last_error,
    )

    memory_state = (
        get_model_state()
    )

    if (
        memory_state.status
        != OCRModelStatus.NOT_STARTED
    ):
        return _state_to_dict(
            memory_state
        )

    return _status_read_error_state(
        last_error
        or RuntimeError(
            (
                "Unknown OCR model "
                "status read error"
            )
        )
    )


_MODEL_STATE = OCRModelState(
    engine=_configured_engine(),
    status=OCRModelStatus.NOT_STARTED,
    message=(
        "OCR model preparation "
        "has not started"
    ),
    error="",
    updated_at=_utc_now_iso(),
)