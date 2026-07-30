import math
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src.logger import create_logger
from src.server.config import (
    CALIBRATED_IMAGES_DIR,
    RAW_IMAGES_DIR,
)


logger = create_logger(
    "processing.calibration"
)


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
}

DEFAULT_OUTPUT_WIDTH = 900
DEFAULT_OUTPUT_HEIGHT = 700

MAX_OUTPUT_DIMENSION = 10000
MAX_OUTPUT_PIXELS = 40_000_000

JPEG_QUALITY = 95
MIN_QUADRILATERAL_AREA = 1.0


class CalibrationError(ValueError):
    """Raised when calibration or image data is invalid."""


def _safe_remove_file(
    file_path: Path | None,
) -> None:
    if file_path is None:
        return

    try:
        if file_path.exists():
            file_path.unlink()

    except OSError:
        logger.exception(
            (
                "Cannot remove temporary "
                "calibrated image: %s"
            ),
            file_path,
        )


def _get_calibration_value(
    calibration: Any,
    field_name: str,
    default: Any = None,
) -> Any:
    if calibration is None:
        return default

    if isinstance(
        calibration,
        Mapping,
    ):
        return calibration.get(
            field_name,
            default,
        )

    getter = getattr(
        calibration,
        "get",
        None,
    )

    if callable(getter):
        try:
            return getter(
                field_name,
                default,
            )

        except TypeError:
            pass

    try:
        return calibration[
            field_name
        ]

    except (
        KeyError,
        IndexError,
        TypeError,
    ):
        return default


def _finite_float(
    value: Any,
    field_name: str,
) -> float:
    try:
        number = float(
            value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise CalibrationError(
            f"{field_name} must be numeric"
        ) from error

    if not math.isfinite(
        number
    ):
        raise CalibrationError(
            f"{field_name} must be finite"
        )

    return number


def _positive_dimension(
    value: Any,
    field_name: str,
    default: int,
) -> int:
    if value in (
        None,
        "",
    ):
        value = default

    try:
        dimension = int(
            value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise CalibrationError(
            f"{field_name} must be an integer"
        ) from error

    if dimension <= 0:
        raise CalibrationError(
            (
                f"{field_name} must be "
                "greater than zero"
            )
        )

    if dimension > MAX_OUTPUT_DIMENSION:
        raise CalibrationError(
            (
                f"{field_name} exceeds "
                f"the maximum of "
                f"{MAX_OUTPUT_DIMENSION}"
            )
        )

    return dimension


def _validate_image(
    image: Any,
    image_name: str = "image",
) -> np.ndarray:
    if not isinstance(
        image,
        np.ndarray,
    ):
        raise CalibrationError(
            (
                f"{image_name} is not "
                "a NumPy image"
            )
        )

    if image.size <= 0:
        raise CalibrationError(
            f"{image_name} is empty"
        )

    if image.ndim not in (
        2,
        3,
    ):
        raise CalibrationError(
            (
                f"{image_name} has "
                "an invalid shape"
            )
        )

    if (
        image.shape[0] <= 0
        or image.shape[1] <= 0
    ):
        raise CalibrationError(
            (
                f"{image_name} has "
                "invalid dimensions"
            )
        )

    return image


def _read_image(
    image_path: Path,
) -> np.ndarray | None:
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

        return None

    if image is not None:
        return image

    # สำรองสำหรับ Path บน Windows
    # ที่ cv2.imread อ่านอักขระบางชนิดไม่ได้
    try:
        encoded_file = np.fromfile(
            str(
                image_path
            ),
            dtype=np.uint8,
        )

        if encoded_file.size <= 0:
            return None

        return cv2.imdecode(
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


def get_latest_file(
    folder,
):
    folder_path = Path(
        folder
    )

    if not folder_path.exists():
        logger.debug(
            (
                "Image folder does not "
                "exist yet: %s"
            ),
            folder_path,
        )

        return None

    if not folder_path.is_dir():
        logger.warning(
            (
                "Image folder path is not "
                "a directory: %s"
            ),
            folder_path,
        )

        return None

    latest_file = None
    latest_key = None

    try:
        candidates = folder_path.rglob(
            "*"
        )

        for file_path in candidates:
            try:
                if not file_path.is_file():
                    continue

                if (
                    file_path.suffix.lower()
                    not in IMAGE_EXTENSIONS
                ):
                    continue

                file_stat = file_path.stat()

                if file_stat.st_size <= 0:
                    continue

                candidate_key = (
                    file_stat.st_mtime_ns,
                    file_path.as_posix(),
                )

                if (
                    latest_key is None
                    or candidate_key
                    > latest_key
                ):
                    latest_key = candidate_key
                    latest_file = file_path

            except (
                FileNotFoundError,
                OSError,
            ):
                # ไฟล์อาจถูก Worker ย้าย
                # ระหว่างกำลังค้นหา
                continue

    except OSError:
        logger.exception(
            (
                "Cannot search image files "
                "in folder: %s"
            ),
            folder_path,
        )

        return None

    if latest_file is None:
        return None

    try:
        relative_path = (
            latest_file.relative_to(
                folder_path
            )
        )

    except ValueError:
        logger.warning(
            (
                "Latest image is outside "
                "the requested folder: %s"
            ),
            latest_file,
        )

        return None

    return relative_path.as_posix()


def build_perspective_points(
    calibration,
):
    if calibration is None:
        raise CalibrationError(
            "Calibration data is required"
        )

    output_width = (
        _positive_dimension(
            _get_calibration_value(
                calibration,
                "output_width",
                DEFAULT_OUTPUT_WIDTH,
            ),
            "output_width",
            DEFAULT_OUTPUT_WIDTH,
        )
    )

    output_height = (
        _positive_dimension(
            _get_calibration_value(
                calibration,
                "output_height",
                DEFAULT_OUTPUT_HEIGHT,
            ),
            "output_height",
            DEFAULT_OUTPUT_HEIGHT,
        )
    )

    if (
        output_width
        * output_height
        > MAX_OUTPUT_PIXELS
    ):
        raise CalibrationError(
            (
                "Calibration output is too large: "
                f"{output_width}x{output_height}"
            )
        )

    point_names = (
        "p1",
        "p2",
        "p3",
        "p4",
    )

    source_values = []

    for point_name in point_names:
        x_name = (
            f"{point_name}_x"
        )

        y_name = (
            f"{point_name}_y"
        )

        source_values.append([
            _finite_float(
                _get_calibration_value(
                    calibration,
                    x_name,
                ),
                x_name,
            ),
            _finite_float(
                _get_calibration_value(
                    calibration,
                    y_name,
                ),
                y_name,
            ),
        ])

    src_points = np.asarray(
        source_values,
        dtype=np.float32,
    )

    unique_points = np.unique(
        src_points,
        axis=0,
    )

    if len(unique_points) != 4:
        raise CalibrationError(
            (
                "Calibration points must "
                "contain four unique points"
            )
        )

    contour = src_points.reshape(
        (-1, 1, 2)
    )

    area = abs(
        float(
            cv2.contourArea(
                contour
            )
        )
    )

    if area <= MIN_QUADRILATERAL_AREA:
        raise CalibrationError(
            (
                "Calibration points form "
                "an invalid or zero-area shape"
            )
        )

    if not cv2.isContourConvex(
        contour
    ):
        raise CalibrationError(
            (
                "Calibration points must be "
                "ordered around a convex shape"
            )
        )

    dst_points = np.asarray(
        [
            [
                0,
                0,
            ],
            [
                output_width - 1,
                0,
            ],
            [
                output_width - 1,
                output_height - 1,
            ],
            [
                0,
                output_height - 1,
            ],
        ],
        dtype=np.float32,
    )

    return (
        src_points,
        dst_points,
        output_width,
        output_height,
    )


def _build_unique_output_path(
    target_folder: Path,
    saved_at: datetime,
) -> Path:
    timestamp_text = (
        saved_at.strftime(
            "%H-%M-%S_%f"
        )
    )

    initial_path = (
        target_folder
        / (
            f"{timestamp_text}"
            "_calibrated.jpg"
        )
    )

    if not initial_path.exists():
        return initial_path

    for number in range(
        1,
        10001,
    ):
        candidate = (
            target_folder
            / (
                f"{timestamp_text}"
                f"_calibrated_{number}.jpg"
            )
        )

        if not candidate.exists():
            return candidate

    raise FileExistsError(
        (
            "Cannot generate a unique "
            "calibrated image filename"
        )
    )


def save_calibrated_image(
    warped_image,
):
    try:
        validated_image = (
            _validate_image(
                warped_image,
                "warped_image",
            )
        )

    except CalibrationError as error:
        logger.warning(
            (
                "Cannot save calibrated "
                "image: %s"
            ),
            error,
        )

        return None

    saved_at = (
        datetime.now()
        .astimezone()
    )

    date_folder = (
        saved_at.strftime(
            "%Y-%m-%d"
        )
    )

    target_folder = (
        CALIBRATED_IMAGES_DIR
        / date_folder
    )

    try:
        target_folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path = (
            _build_unique_output_path(
                target_folder,
                saved_at,
            )
        )

    except OSError:
        logger.exception(
            (
                "Cannot prepare calibrated "
                "image output folder: %s"
            ),
            target_folder,
        )

        return None

    temporary_path = (
        output_path.parent
        / (
            f".{output_path.stem}"
            ".tmp.jpg"
        )
    )

    _safe_remove_file(
        temporary_path
    )

    try:
        save_success = cv2.imwrite(
            str(
                temporary_path
            ),
            validated_image,
            [
                cv2.IMWRITE_JPEG_QUALITY,
                JPEG_QUALITY,
            ],
        )

        if not save_success:
            raise OSError(
                (
                    "OpenCV could not save "
                    "the calibrated image"
                )
            )

        temporary_stat = (
            temporary_path.stat()
        )

        if temporary_stat.st_size <= 0:
            raise OSError(
                (
                    "The temporary calibrated "
                    "image is empty"
                )
            )

        temporary_path.replace(
            output_path
        )

        output_stat = (
            output_path.stat()
        )

        if output_stat.st_size <= 0:
            raise OSError(
                (
                    "The calibrated image "
                    "is empty after saving"
                )
            )

    except (
        OSError,
        cv2.error,
    ):
        logger.exception(
            (
                "Cannot save calibrated "
                "image: %s"
            ),
            output_path,
        )

        _safe_remove_file(
            output_path
        )

        return None

    finally:
        _safe_remove_file(
            temporary_path
        )

    logger.info(
        "Calibrated image saved: %s",
        output_path,
    )

    return output_path


def warp_image_with_calibration(
    image,
    calibration,
):
    validated_image = (
        _validate_image(
            image,
            "source image",
        )
    )

    (
        src_points,
        dst_points,
        output_width,
        output_height,
    ) = build_perspective_points(
        calibration
    )

    try:
        matrix = (
            cv2.getPerspectiveTransform(
                src_points,
                dst_points,
            )
        )

        if (
            matrix is None
            or matrix.shape != (
                3,
                3,
            )
            or not np.isfinite(
                matrix
            ).all()
        ):
            raise CalibrationError(
                (
                    "Perspective transform "
                    "matrix is invalid"
                )
            )

        warped_image = cv2.warpPerspective(
            validated_image,
            matrix,
            (
                output_width,
                output_height,
            ),
        )

    except cv2.error as error:
        raise CalibrationError(
            (
                "OpenCV cannot apply "
                "perspective calibration"
            )
        ) from error

    return _validate_image(
        warped_image,
        "warped image",
    )


def create_calibrated_image(
    raw_image_path,
    calibration,
):
    if calibration is None:
        logger.info(
            (
                "Calibration skipped because "
                "no active calibration exists"
            )
        )

        return None

    raw_path = Path(
        raw_image_path
    )

    if not raw_path.exists():
        logger.warning(
            (
                "Cannot calibrate missing "
                "raw image: %s"
            ),
            raw_path,
        )

        return None

    if not raw_path.is_file():
        logger.warning(
            (
                "Raw image path is not "
                "a file: %s"
            ),
            raw_path,
        )

        return None

    image = _read_image(
        raw_path
    )

    if image is None:
        logger.warning(
            "Cannot read raw image: %s",
            raw_path,
        )

        return None

    logger.info(
        "Starting image calibration: %s",
        raw_path,
    )

    try:
        warped_image = (
            warp_image_with_calibration(
                image=image,
                calibration=calibration,
            )
        )

    except CalibrationError as error:
        logger.warning(
            (
                "Calibration failed for raw "
                "image %s: %s"
            ),
            raw_path,
            error,
        )

        return None

    output_path = save_calibrated_image(
        warped_image
    )

    if output_path is None:
        logger.error(
            (
                "Calibration completed but "
                "the output image could not "
                "be saved: %s"
            ),
            raw_path,
        )

        return None

    logger.info(
        (
            "Image calibration completed: "
            "raw_image=%s, output_image=%s"
        ),
        raw_path,
        output_path,
    )

    return output_path


def create_calibration_preview(
    calibration,
):
    if calibration is None:
        logger.info(
            (
                "Cannot create calibration "
                "preview because no active "
                "calibration exists"
            )
        )

        return {
            "ok": False,
            "message": (
                "No active calibration found"
            ),
        }

    latest_image = get_latest_file(
        RAW_IMAGES_DIR
    )

    if latest_image is None:
        logger.info(
            (
                "Cannot create calibration "
                "preview because no raw "
                "image exists"
            )
        )

        return {
            "ok": False,
            "message": "No raw image found",
        }

    raw_path = (
        RAW_IMAGES_DIR
        / latest_image
    )

    image = _read_image(
        raw_path
    )

    if image is None:
        logger.warning(
            (
                "Cannot create calibration "
                "preview because the raw "
                "image cannot be read: %s"
            ),
            raw_path,
        )

        return {
            "ok": False,
            "message": (
                "Cannot read raw image"
            ),
        }

    logger.info(
        "Creating calibration preview: %s",
        raw_path,
    )

    try:
        warped_image = (
            warp_image_with_calibration(
                image=image,
                calibration=calibration,
            )
        )

    except CalibrationError as error:
        logger.warning(
            (
                "Cannot create calibration "
                "preview for %s: %s"
            ),
            raw_path,
            error,
        )

        return {
            "ok": False,
            "message": (
                "Cannot apply calibration: "
                + str(
                    error
                )
            ),
        }

    output_path = save_calibrated_image(
        warped_image
    )

    if output_path is None:
        return {
            "ok": False,
            "message": (
                "Cannot save calibrated image"
            ),
        }

    try:
        relative_output = (
            output_path.relative_to(
                CALIBRATED_IMAGES_DIR
            )
        )

    except ValueError:
        logger.error(
            (
                "Calibrated preview was saved "
                "outside the configured image "
                "directory: %s"
            ),
            output_path,
        )

        return {
            "ok": False,
            "message": (
                "Invalid calibrated image path"
            ),
        }

    logger.info(
        (
            "Calibration preview created "
            "successfully: %s"
        ),
        output_path,
    )

    return {
        "ok": True,
        "calibrated_image": (
            relative_output.as_posix()
        ),
    }