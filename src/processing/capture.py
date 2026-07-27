import shutil
from datetime import datetime

from src.logger import create_logger
from src.server.config import (
    INCOMING_DIR,
    RAW_IMAGES_DIR
)


logger = create_logger(
    "processing.capture"
)


IMAGE_EXTENSIONS = [
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp"
]


def parse_capture_time_from_filename(filename):
    filename_stem = filename.rsplit(".", 1)[0]

    timestamp_text = filename_stem.replace(
        "_rtsp",
        ""
    )

    try:
        captured_at = datetime.strptime(
            timestamp_text,
            "%Y-%m-%d_%H-%M-%S_%f"
        ).astimezone()

    except ValueError:
        logger.warning(
            (
                "Cannot parse capture time from filename: %s. "
                "Using current time instead."
            ),
            filename
        )

        captured_at = datetime.now().astimezone()

    return captured_at


def capture_image():
    INCOMING_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    RAW_IMAGES_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    try:
        image_files = [
            file_path
            for file_path in INCOMING_DIR.iterdir()
            if (
                file_path.is_file()
                and file_path.suffix.lower()
                in IMAGE_EXTENSIONS
            )
        ]

    except Exception:
        logger.exception(
            "Cannot read incoming image directory"
        )
        return None

    if not image_files:
        return None

    image_file = min(
        image_files,
        key=lambda path: path.stat().st_ctime
    )

    logger.info(
        "Found incoming image: %s",
        image_file.name
    )

    captured_at = parse_capture_time_from_filename(
        image_file.name
    )

    capture_timestamp = int(
        captured_at.timestamp()
    )

    date_folder = captured_at.strftime(
        "%Y-%m-%d"
    )

    target_folder = (
        RAW_IMAGES_DIR
        / date_folder
    )

    target_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    target_path = (
        target_folder
        / image_file.name
    )

    try:
        shutil.move(
            str(image_file),
            str(target_path)
        )

    except Exception:
        logger.exception(
            "Cannot move image to raw_images: %s",
            image_file
        )
        return None

    logger.info(
        (
            "Image moved successfully: "
            "source=%s destination=%s"
        ),
        image_file,
        target_path
    )

    return {
        "image_path": str(target_path),
        "captured_at": captured_at.isoformat(),
        "capture_timestamp": capture_timestamp
    }