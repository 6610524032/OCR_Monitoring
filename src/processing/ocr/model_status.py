import json
import os
import threading

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


class OCRModelStatus(str, Enum):
    NOT_STARTED = "not_started"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"


@dataclass
class OCRModelState:
    engine: str
    status: OCRModelStatus
    message: str
    error: str
    updated_at: str


_MODEL_STATE_LOCK = threading.Lock()

_MODEL_STATE = OCRModelState(
    engine=os.getenv(
        "OCR_ENGINE",
        "trocr",
    ).strip().lower(),
    status=OCRModelStatus.NOT_STARTED,
    message="OCR model preparation has not started",
    error="",
    updated_at=datetime.now(
        timezone.utc
    ).isoformat(),
)


def get_model_cache_dir() -> Path:
    return Path(
        os.getenv(
            "MODEL_CACHE_DIR",
            "/app/model_cache/huggingface",
        )
    )


def get_status_file_path() -> Path:
    return (
        get_model_cache_dir()
        / "ocr_status.json"
    )


def _state_to_dict(
    state: OCRModelState,
) -> dict:
    data = asdict(state)

    data["status"] = state.status.value

    return data


def _write_state_file(
    state: OCRModelState,
) -> None:
    status_file = get_status_file_path()

    status_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = status_file.with_suffix(
        ".json.tmp"
    )

    payload = _state_to_dict(state)

    temporary_file.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary_file.replace(status_file)


def get_model_state() -> OCRModelState:
    with _MODEL_STATE_LOCK:
        return OCRModelState(
            engine=_MODEL_STATE.engine,
            status=_MODEL_STATE.status,
            message=_MODEL_STATE.message,
            error=_MODEL_STATE.error,
            updated_at=_MODEL_STATE.updated_at,
        )


def set_model_status(
    status: OCRModelStatus,
    message: str = "",
    error: str = "",
    engine: Optional[str] = None,
) -> OCRModelState:
    global _MODEL_STATE

    resolved_engine = (
        engine
        or _MODEL_STATE.engine
        or os.getenv(
            "OCR_ENGINE",
            "trocr",
        )
    )

    new_state = OCRModelState(
        engine=str(
            resolved_engine
        ).strip().lower(),
        status=status,
        message=str(message),
        error=str(error),
        updated_at=datetime.now(
            timezone.utc
        ).isoformat(),
    )

    with _MODEL_STATE_LOCK:
        _MODEL_STATE = new_state

        try:
            _write_state_file(new_state)

        except OSError as write_error:
            print(
                "[OCR STATUS] "
                "Cannot write status file:",
                write_error,
            )

    print(
        "[OCR STATUS]",
        new_state.status.value,
        "-",
        new_state.message,
    )

    if new_state.error:
        print(
            "[OCR STATUS ERROR]",
            new_state.error,
        )

    return get_model_state()


def read_model_status_file() -> dict:
    status_file = get_status_file_path()

    if not status_file.exists():
        state = get_model_state()
        return _state_to_dict(state)

    try:
        return json.loads(
            status_file.read_text(
                encoding="utf-8",
            )
        )

    except (
        OSError,
        json.JSONDecodeError,
    ) as read_error:
        return {
            "engine": os.getenv(
                "OCR_ENGINE",
                "trocr",
            ).strip().lower(),
            "status": (
                OCRModelStatus.ERROR.value
            ),
            "message": (
                "Cannot read OCR model status"
            ),
            "error": str(read_error),
            "updated_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }