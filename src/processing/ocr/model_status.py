"""
OCR model loading status.
"""

from dataclasses import dataclass
from enum import Enum


class OCRModelStatus(str, Enum):
    NOT_STARTED = "not_started"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"


@dataclass
class OCRModelState:
    status: OCRModelStatus = OCRModelStatus.NOT_STARTED
    message: str = ""
    error: str = ""


_MODEL_STATE = OCRModelState()


def get_model_state() -> OCRModelState:
    """
    Return current OCR model state.
    """
    return _MODEL_STATE


def set_model_status(
    status: OCRModelStatus,
    message: str = "",
    error: str = "",
) -> None:
    """
    Update OCR model state.
    """
    _MODEL_STATE.status = status
    _MODEL_STATE.message = message
    _MODEL_STATE.error = error