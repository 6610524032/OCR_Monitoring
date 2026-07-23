from datetime import datetime
import time
from urllib.parse import quote

import cv2

from app.server.config import RAW_IMAGES_DIR
from app.server.repositories.camera_repository import (
    get_active_camera
)


def build_rtsp_url(camera):
    camera_ip = str(
        camera.get("camera_ip", "")
    ).strip()

    camera_port = int(
        camera.get("camera_port", 554)
    )

    camera_username = str(
        camera.get("camera_username", "")
    ).strip()

    camera_password = str(
        camera.get("camera_password", "")
    )

    rtsp_path = str(
        camera.get("rtsp_path", "")
    ).strip()

    if not rtsp_path.startswith("/"):
        rtsp_path = "/" + rtsp_path

    username = quote(
        camera_username,
        safe=""
    )

    password = quote(
        camera_password,
        safe=""
    )

    return (
        f"rtsp://{username}:{password}"
        f"@{camera_ip}:{camera_port}"
        f"{rtsp_path}"
    )


def capture_rtsp_image():
    captured_at = datetime.now().astimezone()

    date_folder = captured_at.strftime(
        "%Y-%m-%d"
    )

    save_dir = (
        RAW_IMAGES_DIR
        / date_folder
    )

    try:
        save_dir.mkdir(
            parents=True,
            exist_ok=True
        )

    except Exception as error:
        return {
            "ok": False,
            "stage": "create_directory",
            "message": (
                "Cannot create image directory: "
                + str(error)
            )
        }

    try:
        camera = get_active_camera()

    except Exception as error:
        return {
            "ok": False,
            "stage": "camera_config",
            "message": (
                "Cannot load camera configuration "
                "from database: "
                + str(error)
            )
        }

    if camera is None:
        return {
            "ok": False,
            "stage": "camera_config",
            "message": (
                "Active camera configuration "
                "was not found."
            )
        }

    try:
        rtsp_url = build_rtsp_url(
            camera
        )

    except Exception as error:
        return {
            "ok": False,
            "stage": "build_rtsp_url",
            "message": (
                "Cannot build RTSP URL: "
                + str(error)
            )
        }

    cap = None

    try:
        cap = cv2.VideoCapture(
            rtsp_url,
            cv2.CAP_FFMPEG
        )

        if not cap.isOpened():
            return {
                "ok": False,
                "stage": "open_rtsp",
                "message": (
                    "Cannot open RTSP stream."
                )
            }

        success = False
        frame = None

        for attempt in range(1, 31):
            success, frame = cap.read()

            if (
                success
                and frame is not None
                and frame.size > 0
            ):
                print(
                    "[RTSP CAPTURE] "
                    f"Frame received on "
                    f"attempt {attempt}"
                )
                break

            time.sleep(0.2)

        if (
            not success
            or frame is None
            or frame.size == 0
        ):
            return {
                "ok": False,
                "stage": "read_frame",
                "message": (
                    "RTSP stream opened, "
                    "but no valid frame was received."
                )
            }

    except Exception as error:
        return {
            "ok": False,
            "stage": "rtsp_exception",
            "message": (
                "RTSP capture exception: "
                + str(error)
            )
        }

    finally:
        if cap is not None:
            cap.release()

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

    try:
        saved = cv2.imwrite(
            str(image_path),
            frame
        )

    except Exception as error:
        return {
            "ok": False,
            "stage": "save_image",
            "message": (
                "Image saving exception: "
                + str(error)
            )
        }

    if not saved:
        return {
            "ok": False,
            "stage": "save_image",
            "message": (
                "OpenCV could not save the image: "
                + str(image_path)
            )
        }

    if not image_path.exists():
        return {
            "ok": False,
            "stage": "verify_image",
            "message": (
                "Image file does not exist "
                "after saving: "
                + str(image_path)
            )
        }

    print(
        "[RTSP CAPTURE] "
        f"Image captured: {image_path}"
    )

    return {
        "ok": True,
        "image_path": str(image_path),
        "captured_at": captured_at.isoformat(),
        "capture_timestamp": capture_timestamp
    }


if __name__ == "__main__":
    print(
        capture_rtsp_image()
    )