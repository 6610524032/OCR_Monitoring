import shutil
from datetime import datetime

from app.server.config import (
    INCOMING_DIR,
    RAW_IMAGES_DIR
)

IMAGE_EXTENSIONS = [
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp"
]


def capture_image():
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    RAW_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    image_files = [
        f for f in INCOMING_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    ]

    if not image_files:
        return None

    image_file = min(
        image_files,
        key=lambda x: x.stat().st_ctime
    )

    date_folder = datetime.now().strftime("%Y-%m-%d")
    target_folder = RAW_IMAGES_DIR / date_folder
    target_folder.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%H-%M-%S")
    new_name = f"{timestamp}_{image_file.name}"

    target_path = target_folder / new_name

    shutil.move(
        str(image_file),
        str(target_path)
    )

    return str(target_path)