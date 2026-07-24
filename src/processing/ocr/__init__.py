"""
Generic OCR package.
"""

from src.processing.ocr.service import (
    crop_by_roi,
    read_crop,
    read_manual_roi,
)

__all__ = [
    "crop_by_roi",
    "read_crop",
    "read_manual_roi",
]