from datetime import datetime
import time
from urllib.parse import quote

import cv2

from src.logger import create_logger
from src.server.config import RAW_IMAGES_DIR
from src.server.repositories.camera_repository import (
    get_active_camera
)


logger = create_logger(
    "processing.rtsp_capture"
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

    if not camera_ip:
        raise ValueError(
            "Camera IP is empty"
        )

    if not rtsp_path:
        raise ValueError(
            "RTSP path is empty"
        )

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
    captured_at = (
        datetime.now().astimezone()
    )

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
        logger.exception(
            "Cannot create raw image directory: %s",
            save_dir
        )

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
        logger.exception(
            "Cannot load active camera configuration"
        )

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
        logger.warning(
            "RTSP capture skipped because no active camera was found"
        )

        return {
            "ok": False,
            "stage": "camera_config",
            "message": (
                "Active camera configuration "
                "was not found."
            )
        }

    camera_name = str(
        camera.get(
            "camera_name",
            camera.get(
                "name",
                "Unnamed camera"
            )
        )
    )

    camera_ip = str(
        camera.get(
            "camera_ip",
            ""
        )
    ).strip()

    camera_port = camera.get(
        "camera_port",
        554
    )

    try:
        rtsp_url = build_rtsp_url(
            camera
        )

    except Exception as error:
        logger.exception(
            (
                "Cannot build RTSP URL: "
                "camera=%s, ip=%s, port=%s"
            ),
            camera_name,
            camera_ip,
            camera_port
        )

        return {
            "ok": False,
            "stage": "build_rtsp_url",
            "message": (
                "Cannot build RTSP URL: "
                + str(error)
            )
        }

    logger.info(
        (
            "Starting RTSP capture: "
            "camera=%s, ip=%s, port=%s"
        ),
        camera_name,
        camera_ip,
        camera_port
    )

    cap = None

    try:
        cap = cv2.VideoCapture(
            rtsp_url,
            cv2.CAP_FFMPEG
        )

        if not cap.isOpened():
            logger.error(
                (
                    "Cannot open RTSP stream: "
                    "camera=%s, ip=%s, port=%s"
                ),
                camera_name,
                camera_ip,
                camera_port
            )

            return {
                "ok": False,
                "stage": "open_rtsp",
                "message": (
                    "Cannot open RTSP stream."
                )
            }

        success = False
        frame = None
        successful_attempt = None

        for attempt in range(
            1,
            31
        ):
            success, frame = cap.read()

            if (
                success
                and frame is not None
                and frame.size > 0
            ):
                successful_attempt = attempt
                break

            time.sleep(
                0.2
            )

        if (
            not success
            or frame is None
            or frame.size == 0
        ):
            logger.error(
                (
                    "RTSP stream opened but no valid frame "
                    "was received after 30 attempts: "
                    "camera=%s, ip=%s"
                ),
                camera_name,
                camera_ip
            )

            return {
                "ok": False,
                "stage": "read_frame",
                "message": (
                    "RTSP stream opened, "
                    "but no valid frame was received."
                )
            }

        logger.info(
            (
                "RTSP frame received: "
                "camera=%s, attempt=%s"
            ),
            camera_name,
            successful_attempt
        )

    except Exception as error:
        logger.exception(
            (
                "Unexpected RTSP capture error: "
                "camera=%s, ip=%s"
            ),
            camera_name,
            camera_ip
        )

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

    filename_timestamp = (
        captured_at.strftime(
            "%Y-%m-%d_%H-%M-%S_%f"
        )[:-3]
    )

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
        logger.exception(
            "Image saving exception: %s",
            image_path
        )

        return {
            "ok": False,
            "stage": "save_image",
            "message": (
                "Image saving exception: "
                + str(error)
            )
        }

    if not saved:
        logger.error(
            "OpenCV could not save RTSP image: %s",
            image_path
        )

        return {
            "ok": False,
            "stage": "save_image",
            "message": (
                "OpenCV could not save the image: "
                + str(image_path)
            )
        }

    if not image_path.exists():
        logger.error(
            (
                "RTSP image file was not found "
                "after saving: %s"
            ),
            image_path
        )

        return {
            "ok": False,
            "stage": "verify_image",
            "message": (
                "Image file does not exist "
                "after saving: "
                + str(image_path)
            )
        }

    logger.info(
        (
            "RTSP image captured successfully: "
            "camera=%s, image=%s, "
            "capture_timestamp=%s"
        ),
        camera_name,
        image_path,
        capture_timestamp
    )

    return {
        "ok": True,
        "image_path": str(
            image_path
        ),
        "captured_at": (
            captured_at.isoformat()
        ),
        "capture_timestamp": (
            capture_timestamp
        )
    }


if __name__ == "__main__":
    result = capture_rtsp_image()

    print(
        result
    )