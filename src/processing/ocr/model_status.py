"""
Shared OCR model status definitions.
"""

from enum import Enum


class OCRModelStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    CHECKING = "CHECKING"
    DOWNLOADING = "DOWNLOADING"
    LOADING = "LOADING"
    READY = "READY"
    ERROR = "ERROR"