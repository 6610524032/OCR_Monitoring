from datetime import datetime

import cv2

from app.server.camera_client import (
    CameraConfigError,
    get_camera_config
)
from app.server.config import RAW_IMAGES_DIR


def capture_rtsp_image():

    captured_at = datetime.now().astimezone()

    date_folder = captured_at.strftime(
        "%Y-%m-%d"
    )

    save_dir = (
        RAW_IMAGES_DIR
        / date_folder
    )

    save_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    try:
        camera = get_camera_config()

    except CameraConfigError as error:
        print(
            f"Cannot load camera configuration: {error}"
        )
        return None

    cap = cv2.VideoCapture(
        camera.rtsp_url,
        cv2.CAP_FFMPEG
    )

    success, frame = cap.read()

    cap.release()

    if not success:
        print("Cannot capture image from RTSP")
        return None

    capture_timestamp = int(
        captured_at.timestamp()
    )

    filename_timestamp = captured_at.strftime(
        "%Y-%m-%d_%H-%M-%S_%f"
    )[:-3]

    image_path = (
        save_dir
        / f"{filename_timestamp}_rtsp.jpg"
    )

    saved = cv2.imwrite(
        str(image_path),
        frame
    )

    if not saved:
        print("Cannot save RTSP image")
        return None

    print(
        f"RTSP image captured: {image_path}"
    )

    print(
        f"Capture timestamp: "
        f"{capture_timestamp} "
        f"({captured_at.isoformat()})"
    )

    return {
        "image_path": str(image_path),
        "captured_at": captured_at.isoformat(),
        "capture_timestamp": capture_timestamp
    }


if __name__ == "__main__":
    capture_rtsp_image()