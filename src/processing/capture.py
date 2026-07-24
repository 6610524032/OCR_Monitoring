import shutil
from datetime import datetime

from src.server.config import (
    INCOMING_DIR,
    RAW_IMAGES_DIR
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

    image_files = [
        file_path
        for file_path in INCOMING_DIR.iterdir()
        if (
            file_path.is_file()
            and file_path.suffix.lower()
            in IMAGE_EXTENSIONS
        )
    ]

    if not image_files:
        return None

    image_file = min(
        image_files,
        key=lambda path: path.stat().st_ctime
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

    shutil.move(
        str(image_file),
        str(target_path)
    )

    return {
        "image_path": str(target_path),
        "captured_at": captured_at.isoformat(),
        "capture_timestamp": capture_timestamp
    }