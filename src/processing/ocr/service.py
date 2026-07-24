"""
Generic OCR service.

This module exposes the public OCR API used by the rest of
the application.
"""

from src.processing.ocr_engine import (
    crop_by_roi,
    read_crop,
    read_manual_roi,
)

__all__ = [
    "crop_by_roi",
    "read_crop",
    "read_manual_roi",
]