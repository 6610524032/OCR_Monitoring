from datetime import datetime

import cv2
import numpy as np

from src.logger import create_logger
from src.server.config import (
    CALIBRATED_IMAGES_DIR,
    RAW_IMAGES_DIR
)


logger = create_logger(
    "processing.calibration"
)


IMAGE_EXTENSIONS = [
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp"
]


def get_latest_file(folder):
    if not folder.exists():
        logger.warning(
            "Image folder does not exist: %s",
            folder
        )
        return None

    try:
        image_files = [
            file_path
            for file_path in folder.rglob("*")
            if file_path.is_file()
            and file_path.suffix.lower()
            in IMAGE_EXTENSIONS
        ]

    except Exception:
        logger.exception(
            "Cannot search image files in folder: %s",
            folder
        )
        return None

    if not image_files:
        return None

    try:
        latest_file = max(
            image_files,
            key=lambda file_path: (
                file_path.stat().st_mtime
            )
        )

    except Exception:
        logger.exception(
            "Cannot determine latest image in folder: %s",
            folder
        )
        return None

    return str(
        latest_file.relative_to(folder)
    ).replace(
        "\\",
        "/"
    )


def build_perspective_points(
    calibration
):
    try:
        output_width = int(
            calibration["output_width"]
            or 900
        )

        output_height = int(
            calibration["output_height"]
            or 700
        )

        src_points = np.float32([
            [
                calibration["p1_x"],
                calibration["p1_y"]
            ],
            [
                calibration["p2_x"],
                calibration["p2_y"]
            ],
            [
                calibration["p3_x"],
                calibration["p3_y"]
            ],
            [
                calibration["p4_x"],
                calibration["p4_y"]
            ],
        ])

        dst_points = np.float32([
            [0, 0],
            [output_width, 0],
            [
                output_width,
                output_height
            ],
            [0, output_height],
        ])

    except (
        KeyError,
        TypeError,
        ValueError
    ):
        logger.exception(
            "Invalid calibration data"
        )
        raise

    return (
        src_points,
        dst_points,
        output_width,
        output_height
    )


def save_calibrated_image(
    warped_image
):
    date_folder = datetime.now().strftime(
        "%Y-%m-%d"
    )

    target_folder = (
        CALIBRATED_IMAGES_DIR
        / date_folder
    )

    try:
        target_folder.mkdir(
            parents=True,
            exist_ok=True
        )

    except Exception:
        logger.exception(
            (
                "Cannot create calibrated image "
                "folder: %s"
            ),
            target_folder
        )
        return None

    filename = (
        datetime.now().strftime(
            "%H-%M-%S"
        )
        + "_calibrated.jpg"
    )

    output_path = (
        target_folder
        / filename
    )

    try:
        save_success = cv2.imwrite(
            str(output_path),
            warped_image
        )

    except Exception:
        logger.exception(
            (
                "Unexpected error while saving "
                "calibrated image: %s"
            ),
            output_path
        )
        return None

    if not save_success:
        logger.error(
            "Cannot save calibrated image: %s",
            output_path
        )
        return None

    logger.info(
        "Calibrated image saved: %s",
        output_path
    )

    return output_path


def warp_image_with_calibration(
    image,
    calibration
):
    (
        src_points,
        dst_points,
        output_width,
        output_height
    ) = build_perspective_points(
        calibration
    )

    try:
        matrix = cv2.getPerspectiveTransform(
            src_points,
            dst_points
        )

        warped_image = cv2.warpPerspective(
            image,
            matrix,
            (
                output_width,
                output_height
            )
        )

    except Exception:
        logger.exception(
            "Cannot apply perspective calibration"
        )
        raise

    return warped_image


def create_calibrated_image(
    raw_image_path,
    calibration
):
    if calibration is None:
        logger.warning(
            (
                "Calibration skipped because "
                "no active calibration exists"
            )
        )

        print(
            "No active calibration. "
            "Please set calibration first."
        )

        return None

    image = cv2.imread(
        str(raw_image_path)
    )

    if image is None:
        logger.error(
            "Cannot read raw image: %s",
            raw_image_path
        )

        print(
            "Cannot read raw image"
        )

        return None

    logger.info(
        "Starting image calibration: %s",
        raw_image_path
    )

    try:
        warped_image = (
            warp_image_with_calibration(
                image=image,
                calibration=calibration
            )
        )

    except Exception:
        logger.exception(
            (
                "Calibration failed for "
                "raw image: %s"
            ),
            raw_image_path
        )
        return None

    output_path = save_calibrated_image(
        warped_image
    )

    if output_path is None:
        logger.error(
            (
                "Calibration completed but "
                "output image could not be saved: %s"
            ),
            raw_image_path
        )
        return None

    logger.info(
        (
            "Image calibration completed: "
            "raw_image=%s, output_image=%s"
        ),
        raw_image_path,
        output_path
    )

    return output_path


def create_calibration_preview(
    calibration
):
    latest_image = get_latest_file(
        RAW_IMAGES_DIR
    )

    if latest_image is None:
        logger.warning(
            "Cannot create calibration preview: no raw image found"
        )

        return {
            "ok": False,
            "message": "No raw image found"
        }

    if calibration is None:
        logger.warning(
            (
                "Cannot create calibration preview: "
                "no active calibration found"
            )
        )

        return {
            "ok": False,
            "message": (
                "No active calibration found"
            )
        }

    raw_path = (
        RAW_IMAGES_DIR
        / latest_image
    )

    image = cv2.imread(
        str(raw_path)
    )

    if image is None:
        logger.error(
            (
                "Cannot create calibration preview "
                "because raw image cannot be read: %s"
            ),
            raw_path
        )

        return {
            "ok": False,
            "message": "Cannot read raw image"
        }

    logger.info(
        "Creating calibration preview: %s",
        raw_path
    )

    try:
        warped_image = (
            warp_image_with_calibration(
                image=image,
                calibration=calibration
            )
        )

    except Exception:
        logger.exception(
            (
                "Cannot create calibration preview "
                "for image: %s"
            ),
            raw_path
        )

        return {
            "ok": False,
            "message": (
                "Cannot apply calibration"
            )
        }

    output_path = save_calibrated_image(
        warped_image
    )

    if output_path is None:
        return {
            "ok": False,
            "message": (
                "Cannot save calibrated image"
            )
        }

    relative_output = (
        output_path.relative_to(
            CALIBRATED_IMAGES_DIR
        )
    )

    logger.info(
        (
            "Calibration preview created successfully: "
            "%s"
        ),
        output_path
    )

    return {
        "ok": True,
        "calibrated_image": str(
            relative_output
        ).replace(
            "\\",
            "/"
        )
    }