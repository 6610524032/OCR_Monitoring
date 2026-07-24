"""
OCR provider factory.

Provider selection will be implemented after the TrOCR provider
has been created.
"""

from src.server.config import OCR_ENGINE


SUPPORTED_OCR_ENGINES = {
    "trocr",
}


def validate_ocr_engine() -> str:
    """
    Validate and return the configured OCR engine name.
    """
    if OCR_ENGINE not in SUPPORTED_OCR_ENGINES:
        supported = ", ".join(
            sorted(SUPPORTED_OCR_ENGINES)
        )

        raise ValueError(
            f"Unsupported OCR engine: {OCR_ENGINE}. "
            f"Supported engines: {supported}"
        )

    return OCR_ENGINE