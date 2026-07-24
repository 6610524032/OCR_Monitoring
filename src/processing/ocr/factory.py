"""
OCR provider factory.

This module selects and returns the OCR provider configured
through the OCR_ENGINE environment setting.
"""

from typing import Any, Optional

from src.processing.ocr.providers.trocr_provider import (
    get_trocr_provider,
)
from src.server.config import OCR_ENGINE


SUPPORTED_OCR_ENGINES = {
    "trocr",
}


_OCR_PROVIDER: Optional[Any] = None
_ACTIVE_OCR_ENGINE: Optional[str] = None


def validate_ocr_engine() -> str:
    """
    Validate and return the configured OCR engine name.
    """
    engine_name = str(
        OCR_ENGINE
    ).strip().lower()

    if engine_name not in SUPPORTED_OCR_ENGINES:
        supported = ", ".join(
            sorted(SUPPORTED_OCR_ENGINES)
        )

        raise ValueError(
            f"Unsupported OCR engine: {engine_name}. "
            f"Supported engines: {supported}"
        )

    return engine_name


def create_ocr_provider() -> Any:
    """
    Create the OCR provider selected by OCR_ENGINE.
    """
    engine_name = validate_ocr_engine()

    if engine_name == "trocr":
        return get_trocr_provider()

    raise ValueError(
        f"No provider implementation found "
        f"for OCR engine: {engine_name}"
    )


def get_ocr_provider() -> Any:
    """
    Return the shared OCR provider instance.

    The provider is recreated only if the configured OCR engine
    changes during the current Python process.
    """
    global _OCR_PROVIDER
    global _ACTIVE_OCR_ENGINE

    engine_name = validate_ocr_engine()

    if (
        _OCR_PROVIDER is None
        or _ACTIVE_OCR_ENGINE != engine_name
    ):
        _OCR_PROVIDER = create_ocr_provider()
        _ACTIVE_OCR_ENGINE = engine_name

    return _OCR_PROVIDER


def get_active_ocr_engine() -> str:
    """
    Return the validated active OCR engine name.
    """
    return validate_ocr_engine()