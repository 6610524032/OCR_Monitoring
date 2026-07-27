import re

import cv2
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


def normalize_text(text):
    text = str(text).strip().replace(
        " ",
        ""
    )
    text = text.replace(
        ",",
        "."
    )
    text = text.replace(
        "O",
        "0"
    ).replace(
        "o",
        "0"
    )

    return text


def extract_value(text):
    raw_text = str(
        text
    ).strip()

    if not re.search(
        r"\d",
        raw_text
    ):
        return ""

    text = normalize_text(
        raw_text
    )

    patterns = [
        r"\d+(?::\d+)+",
        r"\d+(?:[/-]\d+)+",
        r"\d+\.\d+",
        r"\d+",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text
        )

        if match:
            return match.group(
                0
            )

    return ""


def prepare_crop(crop):
    if (
        crop is None
        or crop.size == 0
    ):
        logger.warning(
            "Cannot prepare OCR crop because crop is empty"
        )
        return None

    try:
        crop = cv2.copyMakeBorder(
            crop,
            12,
            12,
            12,
            12,
            cv2.BORDER_CONSTANT,
            value=(255, 255, 255),
        )

        crop = cv2.resize(
            crop,
            None,
            fx=4,
            fy=4,
            interpolation=cv2.INTER_CUBIC,
        )

        rgb = cv2.cvtColor(
            crop,
            cv2.COLOR_BGR2RGB,
        )

        return Image.fromarray(
            rgb
        )

    except Exception:
        logger.exception(
            "Cannot prepare OCR crop"
        )
        return None


def crop_image(
    image,
    x1,
    y1,
    x2,
    y2,
):
    if image is None:
        logger.error(
            "Cannot crop image because image is None"
        )
        return None

    try:
        image_h, image_w = (
            image.shape[:2]
        )

        x1 = int(
            round(
                float(x1)
            )
        )
        y1 = int(
            round(
                float(y1)
            )
        )
        x2 = int(
            round(
                float(x2)
            )
        )
        y2 = int(
            round(
                float(y2)
            )
        )

    except (
        TypeError,
        ValueError,
        AttributeError
    ):
        logger.exception(
            (
                "Invalid ROI coordinates: "
                "x1=%r, y1=%r, x2=%r, y2=%r"
            ),
            x1,
            y1,
            x2,
            y2
        )
        return None

    x1, x2 = sorted([
        x1,
        x2
    ])
    y1, y2 = sorted([
        y1,
        y2
    ])

    x1 = max(
        0,
        min(
            image_w,
            x1
        )
    )
    x2 = max(
        0,
        min(
            image_w,
            x2
        )
    )
    y1 = max(
        0,
        min(
            image_h,
            y1
        )
    )
    y2 = max(
        0,
        min(
            image_h,
            y2
        )
    )

    if (
        x2 <= x1
        or y2 <= y1
    ):
        logger.warning(
            (
                "Invalid or empty ROI after boundary check: "
                "x1=%d, y1=%d, x2=%d, y2=%d, "
                "image_width=%d, image_height=%d"
            ),
            x1,
            y1,
            x2,
            y2,
            image_w,
            image_h
        )
        return None

    return image[
        y1:y2,
        x1:x2,
    ]


def crop_by_roi(
    image,
    tag
):
    tag_name = str(
        tag.get(
            "tag_name",
            "Unknown tag"
        )
    )

    try:
        return crop_image(
            image=image,
            x1=tag["roi_x1"],
            y1=tag["roi_y1"],
            x2=tag["roi_x2"],
            y2=tag["roi_y2"],
        )

    except KeyError:
        logger.exception(
            (
                "ROI coordinates are incomplete "
                "for tag: %s"
            ),
            tag_name
        )
        return None


def read_crop(crop):
    if (
        crop is None
        or crop.size == 0
    ):
        logger.warning(
            "OCR skipped because crop is empty"
        )

        return {
            "ok": False,
            "value": "",
            "raw_text": "",
            "message": "Empty crop",
        }

    try:
        pil_image = prepare_crop(
            crop
        )

        if pil_image is None:
            logger.error(
                "OCR crop preparation failed"
            )

            return {
                "ok": False,
                "value": "",
                "raw_text": "",
                "message": (
                    "Cannot prepare crop"
                ),
            }

        provider = get_ocr_provider()

        raw_text = provider.read(
            pil_image,
        )

        value = extract_value(
            raw_text
        )

        if value == "":
            logger.warning(
                (
                    "OCR returned text but no numeric "
                    "value could be extracted: raw_text=%r"
                ),
                raw_text
            )

        return {
            "ok": True,
            "value": value,
            "raw_text": raw_text,
            "message": "success",
        }

    except Exception as error:
        logger.exception(
            "Unexpected OCR read error"
        )

        return {
            "ok": False,
            "value": "",
            "raw_text": "",
            "message": str(
                error
            ),
        }


def read_manual_roi(
    image_name,
    x1,
    y1,
    x2,
    y2,
):
    logger.info(
        (
            "Manual ROI OCR requested: "
            "image=%s, x1=%s, y1=%s, "
            "x2=%s, y2=%s"
        ),
        image_name,
        x1,
        y1,
        x2,
        y2
    )

    image_path = (
        CALIBRATED_IMAGES_DIR
        / image_name
    )

    if not image_path.exists():
        logger.warning(
            (
                "Manual ROI OCR failed because "
                "image was not found: %s"
            ),
            image_path
        )

        return {
            "ok": False,
            "message": "Image not found",
        }

    image = cv2.imread(
        str(image_path)
    )

    if image is None:
        logger.error(
            (
                "Manual ROI OCR failed because "
                "image cannot be read: %s"
            ),
            image_path
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

    result = read_crop(
        crop
    )

    if not result.get(
        "ok"
    ):
        error_message = result.get(
            "message",
            "OCR failed",
        )

        logger.warning(
            (
                "Manual ROI OCR failed: "
                "image=%s, error=%s"
            ),
            image_path,
            error_message
        )

        return {
            "ok": False,
            "message": error_message,
        }

    logger.info(
        (
            "Manual ROI OCR completed successfully: "
            "image=%s, value=%r"
        ),
        image_path,
        result.get(
            "value",
            ""
        )
    )

    return {
        "ok": True,
        "text": result.get(
            "value",
            "",
        ),
        "raw_text": result.get(
            "raw_text",
            "",
        ),
    }