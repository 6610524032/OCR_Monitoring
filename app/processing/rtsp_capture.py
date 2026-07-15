from datetime import datetime

import cv2

from app.server.camera_client import (
    CameraConfigError,
    get_camera_config
)
from app.server.config import INCOMING_DIR


def capture_rtsp_image():
    INCOMING_DIR.mkdir(
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

    timestamp = datetime.now().strftime(
        "%Y-%m-%d_%H-%M-%S"
    )

    image_path = (
        INCOMING_DIR
        / f"{timestamp}_rtsp.jpg"
    )

    saved = cv2.imwrite(
        str(image_path),
        frame
    )

    if not saved:
        print("Cannot save RTSP image")
        return None

    print(f"RTSP image captured: {image_path}")

    return image_path


if __name__ == "__main__":
    capture_rtsp_image()