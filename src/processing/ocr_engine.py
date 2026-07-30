import math
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Any

import cv2
import numpy as np
from PIL import Image

from src.logger import create_logger
from src.processing.ocr.factory import (
    get_ocr_provider,
)
from src.server.config import (
    CALIBRATED_IMAGES_DIR,
)


logger = create_logger(
    "processing.ocr_engine"
)


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
}

OCR_BORDER_SIZE = 12
OCR_RESIZE_SCALE = 4.0

MAX_PREPARED_DIMENSION = 4096
MAX_PREPARED_PIXELS = 16_000_000
MAX_SOURCE_PIXELS = 40_000_000

MAX_OCR_TEXT_LENGTH = 500
MAX_IMAGE_NAME_LENGTH = 1024


_OCR_READ_LOCK = Lock()

_CONTROL_CHAR_PATTERN = re.compile(
    r"[\x00-\x1f\x7f]"
)

_DIGIT_PATTERN = re.compile(
    r"\d"
)

_VALUE_PATTERNS = (
    re.compile(
        r"[-+]?\d+(?::\d+)+"
    ),
    re.compile(
        r"[-+]?\d+(?:[/-]\d+)+"
    ),
    re.compile(
        r"[-+]?(?:\d+\.\d+|\.\d+)"
    ),
    re.compile(
        r"[-+]?\d+"
    ),
)


class OCRInputError(ValueError):
    """
    Raised when OCR input data is invalid.
    """


def _result(
    ok: bool,
    value: str = "",
    raw_text: str = "",
    message: str = "",
) -> dict[str, Any]:
    return {
        "ok": ok,
        "value": value,
        "raw_text": raw_text,
        "message": message,
    }


def _safe_text(
    value: Any,
    max_length: int = MAX_OCR_TEXT_LENGTH,
) -> str:
    if value is None:
        return ""

    try:
        text = str(
            value
        )

    except Exception:
        return ""

    text = unicodedata.normalize(
        "NFKC",
        text,
    )

    text = _CONTROL_CHAR_PATTERN.sub(
        "",
        text,
    ).strip()

    return text[
        :max_length
    ]


def normalize_text(
    text,
):
    normalized = _safe_text(
        text
    )

    normalized = "".join(
        normalized.split()
    )

    normalized = (
        normalized.replace(
            "−",
            "-",
        )
        .replace(
            "–",
            "-",
        )
        .replace(
            "—",
            "-",
        )
        .replace(
            ",",
            ".",
        )
        .replace(
            "O",
            "0",
        )
        .replace(
            "o",
            "0",
        )
    )

    return normalized


def extract_value(
    text,
):
    normalized = normalize_text(
        text
    )

    if not normalized:
        return ""

    if not _DIGIT_PATTERN.search(
        normalized
    ):
        return ""

    for pattern in _VALUE_PATTERNS:
        match = pattern.search(
            normalized
        )

        if match is not None:
            return match.group(
                0
            )

    return ""


def _is_valid_image(
    image: Any,
) -> bool:
    if not isinstance(
        image,
        np.ndarray,
    ):
        return False

    if image.size <= 0:
        return False

    if image.ndim not in (
        2,
        3,
    ):
        return False

    if (
        image.shape[0] <= 0
        or image.shape[1] <= 0
    ):
        return False

    if (
        image.shape[0]
        * image.shape[1]
        > MAX_SOURCE_PIXELS
    ):
        return False

    return True


def _to_uint8(
    image: np.ndarray,
) -> np.ndarray:
    if image.dtype == np.uint8:
        return image

    converted = np.nan_to_num(
        image,
        nan=0.0,
        posinf=255.0,
        neginf=0.0,
    )

    if np.issubdtype(
        converted.dtype,
        np.floating,
    ):
        maximum = float(
            converted.max()
        )

        if maximum <= 1.0:
            converted = (
                converted
                * 255.0
            )

    return np.clip(
        converted,
        0,
        255,
    ).astype(
        np.uint8
    )


def _calculate_resize_dimensions(
    width: int,
    height: int,
) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise OCRInputError(
            "OCR crop has invalid dimensions"
        )

    scale = OCR_RESIZE_SCALE

    scale = min(
        scale,
        MAX_PREPARED_DIMENSION
        / max(
            width,
            height,
        ),
    )

    source_pixels = (
        width
        * height
    )

    if source_pixels > 0:
        scale = min(
            scale,
            math.sqrt(
                MAX_PREPARED_PIXELS
                / source_pixels
            ),
        )

    if not math.isfinite(
        scale
    ) or scale <= 0:
        raise OCRInputError(
            "Cannot calculate OCR resize scale"
        )

    target_width = max(
        1,
        int(
            round(
                width
                * scale
            )
        ),
    )

    target_height = max(
        1,
        int(
            round(
                height
                * scale
            )
        ),
    )

    return (
        target_width,
        target_height,
    )


def prepare_crop(
    crop,
):
    if not _is_valid_image(
        crop
    ):
        logger.warning(
            (
                "Cannot prepare OCR crop "
                "because the crop is invalid"
            )
        )

        return None

    try:
        prepared = _to_uint8(
            crop
        )

        prepared = cv2.copyMakeBorder(
            prepared,
            OCR_BORDER_SIZE,
            OCR_BORDER_SIZE,
            OCR_BORDER_SIZE,
            OCR_BORDER_SIZE,
            cv2.BORDER_CONSTANT,
            value=(
                255,
                255,
                255,
            ),
        )

        height, width = (
            prepared.shape[:2]
        )

        (
            target_width,
            target_height,
        ) = _calculate_resize_dimensions(
            width=width,
            height=height,
        )

        if (
            target_width != width
            or target_height != height
        ):
            interpolation = (
                cv2.INTER_CUBIC
                if (
                    target_width >= width
                    and target_height >= height
                )
                else cv2.INTER_AREA
            )

            prepared = cv2.resize(
                prepared,
                (
                    target_width,
                    target_height,
                ),
                interpolation=interpolation,
            )

        if prepared.ndim == 2:
            rgb = cv2.cvtColor(
                prepared,
                cv2.COLOR_GRAY2RGB,
            )

        elif (
            prepared.ndim == 3
            and prepared.shape[2] == 3
        ):
            rgb = cv2.cvtColor(
                prepared,
                cv2.COLOR_BGR2RGB,
            )

        elif (
            prepared.ndim == 3
            and prepared.shape[2] == 4
        ):
            rgb = cv2.cvtColor(
                prepared,
                cv2.COLOR_BGRA2RGB,
            )

        else:
            logger.warning(
                (
                    "Cannot prepare OCR crop "
                    "because the channel count "
                    "is unsupported"
                )
            )

            return None

        return Image.fromarray(
            rgb
        )

    except (
        OCRInputError,
        cv2.error,
        MemoryError,
        TypeError,
        ValueError,
    ):
        logger.exception(
            "Cannot prepare OCR crop"
        )

        return None


def _finite_coordinate(
    value: Any,
    field_name: str,
) -> float:
    if isinstance(
        value,
        bool,
    ):
        raise OCRInputError(
            f"{field_name} must be numeric"
        )

    try:
        coordinate = float(
            value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise OCRInputError(
            f"{field_name} must be numeric"
        ) from error

    if not math.isfinite(
        coordinate
    ):
        raise OCRInputError(
            f"{field_name} must be finite"
        )

    return coordinate


def crop_image(
    image,
    x1,
    y1,
    x2,
    y2,
):
    if not _is_valid_image(
        image
    ):
        logger.warning(
            (
                "Cannot crop OCR image "
                "because the image is invalid"
            )
        )

        return None

    try:
        image_height, image_width = (
            image.shape[:2]
        )

        left = int(
            round(
                _finite_coordinate(
                    x1,
                    "x1",
                )
            )
        )

        top = int(
            round(
                _finite_coordinate(
                    y1,
                    "y1",
                )
            )
        )

        right = int(
            round(
                _finite_coordinate(
                    x2,
                    "x2",
                )
            )
        )

        bottom = int(
            round(
                _finite_coordinate(
                    y2,
                    "y2",
                )
            )
        )

    except OCRInputError as error:
        logger.warning(
            (
                "Invalid OCR ROI "
                "coordinates: %s"
            ),
            error,
        )

        return None

    left, right = sorted(
        (
            left,
            right,
        )
    )

    top, bottom = sorted(
        (
            top,
            bottom,
        )
    )

    left = max(
        0,
        min(
            image_width,
            left,
        ),
    )

    right = max(
        0,
        min(
            image_width,
            right,
        ),
    )

    top = max(
        0,
        min(
            image_height,
            top,
        ),
    )

    bottom = max(
        0,
        min(
            image_height,
            bottom,
        ),
    )

    if (
        right <= left
        or bottom <= top
    ):
        logger.warning(
            (
                "OCR ROI is empty after "
                "boundary validation: "
                "x1=%d, y1=%d, x2=%d, y2=%d, "
                "image_width=%d, image_height=%d"
            ),
            left,
            top,
            right,
            bottom,
            image_width,
            image_height,
        )

        return None

    crop = image[
        top:bottom,
        left:right,
    ]

    if not _is_valid_image(
        crop
    ):
        return None

    return np.ascontiguousarray(
        crop
    )


def _tag_value(
    tag: Any,
    field_name: str,
    fallback_name: str | None = None,
) -> Any:
    if isinstance(
        tag,
        Mapping,
    ):
        if field_name in tag:
            return tag[
                field_name
            ]

        if (
            fallback_name is not None
            and fallback_name in tag
        ):
            return tag[
                fallback_name
            ]

        raise KeyError(
            field_name
        )

    getter = getattr(
        tag,
        "get",
        None,
    )

    if callable(
        getter
    ):
        sentinel = object()

        value = getter(
            field_name,
            sentinel,
        )

        if value is not sentinel:
            return value

        if fallback_name is not None:
            value = getter(
                fallback_name,
                sentinel,
            )

            if value is not sentinel:
                return value

    try:
        return tag[
            field_name
        ]

    except (
        KeyError,
        IndexError,
        TypeError,
    ):
        if fallback_name is not None:
            try:
                return tag[
                    fallback_name
                ]

            except (
                KeyError,
                IndexError,
                TypeError,
            ):
                pass

    raise KeyError(
        field_name
    )


def crop_by_roi(
    image,
    tag,
):
    if tag is None:
        logger.warning(
            (
                "Cannot crop OCR ROI "
                "because tag is missing"
            )
        )

        return None

    try:
        tag_name = _safe_text(
            _tag_value(
                tag,
                "tag_name",
                "display_name",
            ),
            max_length=150,
        ) or "Unknown tag"

    except KeyError:
        tag_name = "Unknown tag"

    try:
        return crop_image(
            image=image,
            x1=_tag_value(
                tag,
                "roi_x1",
                "x1",
            ),
            y1=_tag_value(
                tag,
                "roi_y1",
                "y1",
            ),
            x2=_tag_value(
                tag,
                "roi_x2",
                "x2",
            ),
            y2=_tag_value(
                tag,
                "roi_y2",
                "y2",
            ),
        )

    except KeyError as error:
        logger.warning(
            (
                "ROI coordinates are incomplete "
                "for tag %s: missing=%s"
            ),
            tag_name,
            error,
        )

        return None


def read_crop(
    crop,
):
    if not _is_valid_image(
        crop
    ):
        logger.warning(
            (
                "OCR skipped because "
                "the crop is invalid"
            )
        )

        return _result(
            ok=False,
            message=(
                "Empty or invalid crop"
            ),
        )

    pil_image = prepare_crop(
        crop
    )

    if pil_image is None:
        return _result(
            ok=False,
            message="Cannot prepare crop",
        )

    try:
        with _OCR_READ_LOCK:
            provider = (
                get_ocr_provider()
            )

            read_method = getattr(
                provider,
                "read",
                None,
            )

            if not callable(
                read_method
            ):
                raise RuntimeError(
                    (
                        "OCR provider does not "
                        "implement read()"
                    )
                )

            provider_text = read_method(
                pil_image
            )

        raw_text = _safe_text(
            provider_text
        )

        value = extract_value(
            raw_text
        )

        if not value:
            logger.debug(
                (
                    "OCR completed but no "
                    "numeric value was extracted"
                )
            )

            return _result(
                ok=True,
                value="",
                raw_text=raw_text,
                message=(
                    "No numeric value found"
                ),
            )

        return _result(
            ok=True,
            value=value,
            raw_text=raw_text,
            message="success",
        )

    except MemoryError:
        logger.exception(
            (
                "OCR processing failed because "
                "available memory was insufficient"
            )
        )

        return _result(
            ok=False,
            message="OCR memory error",
        )

    except Exception:
        logger.exception(
            "Unexpected OCR read error"
        )

        return _result(
            ok=False,
            message=(
                "OCR processing failed"
            ),
        )

    finally:
        try:
            pil_image.close()

        except Exception:
            logger.debug(
                "Cannot close OCR PIL image"
            )


def _resolve_calibrated_image_path(
    image_name: Any,
) -> Path:
    if not isinstance(
        image_name,
        str,
    ):
        raise OCRInputError(
            "Image name must be a string"
        )

    normalized = (
        image_name.strip()
        .replace(
            "\\",
            "/",
        )
    )

    if not normalized:
        raise OCRInputError(
            "Image name is required"
        )

    if "\x00" in normalized:
        raise OCRInputError(
            (
                "Image name contains "
                "an invalid character"
            )
        )

    if len(
        normalized
    ) > MAX_IMAGE_NAME_LENGTH:
        raise OCRInputError(
            "Image name is too long"
        )

    relative_path = Path(
        normalized
    )

    if relative_path.is_absolute():
        raise OCRInputError(
            "Image path must be relative"
        )

    if ".." in relative_path.parts:
        raise OCRInputError(
            (
                "Image path cannot leave "
                "the image directory"
            )
        )

    if (
        relative_path.parts
        and ":" in relative_path.parts[0]
    ):
        raise OCRInputError(
            (
                "Image path cannot contain "
                "a drive path"
            )
        )

    if (
        relative_path.suffix.lower()
        not in IMAGE_EXTENSIONS
    ):
        raise OCRInputError(
            (
                "Image file type "
                "is not supported"
            )
        )

    base_directory = Path(
        CALIBRATED_IMAGES_DIR
    ).resolve()

    candidate = (
        base_directory
        / relative_path
    ).resolve()

    try:
        candidate.relative_to(
            base_directory
        )

    except ValueError as error:
        raise OCRInputError(
            (
                "Image path is outside the "
                "calibrated image directory"
            )
        ) from error

    return candidate


def _read_image(
    image_path: Path,
):
    try:
        image = cv2.imread(
            str(
                image_path
            ),
            cv2.IMREAD_COLOR,
        )

    except cv2.error:
        logger.exception(
            "OpenCV cannot read image: %s",
            image_path,
        )

        image = None

    if _is_valid_image(
        image
    ):
        return image

    try:
        encoded_file = np.fromfile(
            str(
                image_path
            ),
            dtype=np.uint8,
        )

        if encoded_file.size <= 0:
            return None

        image = cv2.imdecode(
            encoded_file,
            cv2.IMREAD_COLOR,
        )

    except (
        OSError,
        ValueError,
        cv2.error,
    ):
        logger.exception(
            "Cannot decode image file: %s",
            image_path,
        )

        return None

    if not _is_valid_image(
        image
    ):
        return None

    return image


def read_manual_roi(
    image_name,
    x1,
    y1,
    x2,
    y2,
):
    try:
        image_path = (
            _resolve_calibrated_image_path(
                image_name
            )
        )

    except OCRInputError as error:
        logger.warning(
            (
                "Manual ROI OCR rejected: %s"
            ),
            error,
        )

        return {
            "ok": False,
            "message": str(
                error
            ),
        }

    logger.info(
        (
            "Manual ROI OCR requested: "
            "image=%s"
        ),
        image_path.name,
    )

    if not image_path.exists():
        logger.warning(
            (
                "Manual ROI OCR image was "
                "not found: %s"
            ),
            image_path,
        )

        return {
            "ok": False,
            "message": "Image not found",
        }

    if not image_path.is_file():
        logger.warning(
            (
                "Manual ROI OCR path is not "
                "a file: %s"
            ),
            image_path,
        )

        return {
            "ok": False,
            "message": "Invalid image path",
        }

    image = _read_image(
        image_path
    )

    if image is None:
        logger.warning(
            (
                "Manual ROI OCR image cannot "
                "be read: %s"
            ),
            image_path,
        )

        return {
            "ok": False,
            "message": "Cannot read image",
        }

    crop = crop_image(
        image=image,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
    )

    if crop is None:
        return {
            "ok": False,
            "message": (
                "Invalid or empty ROI"
            ),
        }

    result = read_crop(
        crop
    )

    if not result.get(
        "ok"
    ):
        error_message = _safe_text(
            result.get(
                "message",
                "OCR failed",
            ),
            max_length=200,
        ) or "OCR failed"

        logger.warning(
            (
                "Manual ROI OCR failed: "
                "image=%s, error=%s"
            ),
            image_path,
            error_message,
        )

        return {
            "ok": False,
            "message": error_message,
        }

    value = _safe_text(
        result.get(
            "value",
            "",
        )
    )

    raw_text = _safe_text(
        result.get(
            "raw_text",
            "",
        )
    )

    logger.info(
        (
            "Manual ROI OCR completed: "
            "image=%s, value_found=%s"
        ),
        image_path.name,
        bool(
            value
        ),
    )

    return {
        "ok": True,
        "text": value,
        "value": value,
        "raw_text": raw_text,
        "message": result.get(
            "message",
            "success",
        ),
    }