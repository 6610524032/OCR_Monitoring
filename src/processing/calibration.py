from datetime import datetime

import cv2
import numpy as np

from src.server.config import (
    CALIBRATED_IMAGES_DIR,
    RAW_IMAGES_DIR
)


IMAGE_EXTENSIONS = [
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp"
]


def get_latest_file(folder):
    if not folder.exists():
        return None

    image_files = [
        file_path for file_path in folder.rglob("*")
        if file_path.is_file()
        and file_path.suffix.lower() in IMAGE_EXTENSIONS
    ]

    if not image_files:
        return None

    latest_file = max(
        image_files,
        key=lambda file_path: file_path.stat().st_mtime
    )

    return str(latest_file.relative_to(folder)).replace("\\", "/")


def build_perspective_points(calibration):
    output_width = int(calibration["output_width"] or 900)
    output_height = int(calibration["output_height"] or 700)

    src_points = np.float32([
        [calibration["p1_x"], calibration["p1_y"]],
        [calibration["p2_x"], calibration["p2_y"]],
        [calibration["p3_x"], calibration["p3_y"]],
        [calibration["p4_x"], calibration["p4_y"]],
    ])

    dst_points = np.float32([
        [0, 0],
        [output_width, 0],
        [output_width, output_height],
        [0, output_height],
    ])

    return src_points, dst_points, output_width, output_height


def save_calibrated_image(warped_image):
    date_folder = datetime.now().strftime("%Y-%m-%d")
    target_folder = CALIBRATED_IMAGES_DIR / date_folder
    target_folder.mkdir(parents=True, exist_ok=True)

    filename = datetime.now().strftime("%H-%M-%S") + "_calibrated.jpg"
    output_path = target_folder / filename

    cv2.imwrite(str(output_path), warped_image)

    return output_path


def warp_image_with_calibration(image, calibration):
    src_points, dst_points, output_width, output_height = build_perspective_points(
        calibration
    )

    matrix = cv2.getPerspectiveTransform(
        src_points,
        dst_points
    )

    return cv2.warpPerspective(
        image,
        matrix,
        (output_width, output_height)
    )


def create_calibrated_image(raw_image_path, calibration):
    if calibration is None:
        print("No active calibration. Please set calibration first.")
        return None

    image = cv2.imread(str(raw_image_path))

    if image is None:
        print("Cannot read raw image")
        return None

    warped_image = warp_image_with_calibration(
        image=image,
        calibration=calibration
    )

    return save_calibrated_image(warped_image)


def create_calibration_preview(calibration):
    latest_image = get_latest_file(RAW_IMAGES_DIR)

    if latest_image is None:
        return {
            "ok": False,
            "message": "No raw image found"
        }

    if calibration is None:
        return {
            "ok": False,
            "message": "No active calibration found"
        }

    raw_path = RAW_IMAGES_DIR / latest_image
    image = cv2.imread(str(raw_path))

    if image is None:
        return {
            "ok": False,
            "message": "Cannot read raw image"
        }

    warped_image = warp_image_with_calibration(
        image=image,
        calibration=calibration
    )

    output_path = save_calibrated_image(warped_image)

    relative_output = output_path.relative_to(
        CALIBRATED_IMAGES_DIR
    )

    return {
        "ok": True,
        "calibrated_image": str(relative_output).replace("\\", "/")
    }