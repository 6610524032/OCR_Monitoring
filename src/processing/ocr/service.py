"""
Generic OCR service.

During the first migration step, this module delegates OCR work
to the existing OCR engine. Later, it will delegate through the
OCR factory and provider architecture.
"""

from typing import Any

from src.processing.ocr_engine import (
    crop_by_roi as legacy_crop_by_roi,
    read_crop as legacy_read_crop,
    read_manual_roi as legacy_read_manual_roi,
)


def crop_by_roi(
    image: Any,
    tag: dict[str, Any],
) -> Any:
    """
    Crop an image using ROI data.

    This wrapper keeps the rest of the application independent
    from the current OCR implementation module.
    """
    return legacy_crop_by_roi(
        image,
        tag,
    )


def read_crop(crop: Any) -> dict[str, Any]:
    """
    Read text from a cropped image using the active OCR engine.
    """
    return legacy_read_crop(crop)


def read_manual_roi(
    image_name: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
) -> dict[str, Any]:
    """
    Run OCR for a manually selected ROI.
    """
    return legacy_read_manual_roi(
        image_name,
        x1,
        y1,
        x2,
        y2,
    )