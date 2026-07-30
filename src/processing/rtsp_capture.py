import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2

from src.logger import create_logger
from src.server.camera_client import (
    CameraConfigError,
    build_rtsp_url as build_camera_rtsp_url,
)
from src.server.config import RAW_IMAGES_DIR
from src.server.repositories.camera_repository import (
    get_active_camera,
)


logger = create_logger(
    "processing.rtsp_capture"
)


RTSP_OPEN_TIMEOUT_MS = 15000
RTSP_READ_TIMEOUT_MS = 10000

FRAME_READ_ATTEMPTS = 30
FRAME_RETRY_DELAY_SECONDS = 0.2

JPEG_QUALITY = 95


def _failure_result(
    stage: str,
    message: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "stage": stage,
        "message": message,
    }


def _safe_release_capture(
    cap,
) -> None:
    if cap is None:
        return

    try:
        cap.release()

    except Exception:
        logger.exception(
            (
                "Failed to release "
                "RTSP capture"
            )
        )


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
                "Failed to remove temporary "
                "image file: %s"
            ),
            file_path,
        )


def _camera_value(
    camera,
    field_name: str,
    default: Any = "",
) -> Any:
    if camera is None:
        return default

    getter = getattr(
        camera,
        "get",
        None,
    )

    if callable(getter):
        return getter(
            field_name,
            default,
        )

    try:
        return camera[
            field_name
        ]

    except (
        KeyError,
        IndexError,
        TypeError,
    ):
        return default


def build_rtsp_url(
    camera,
) -> str:
    """
    Build an RTSP URL from a camera
    repository record.

    The shared camera-client URL builder
    performs validation and safely encodes
    the username and password.
    """
    if camera is None:
        raise ValueError(
            (
                "Camera configuration "
                "is required"
            )
        )

    camera_ip = _camera_value(
        camera,
        "camera_ip",
        "",
    )

    camera_port = _camera_value(
        camera,
        "camera_port",
        554,
    )

    camera_username = _camera_value(
        camera,
        "camera_username",
        "",
    )

    camera_password = _camera_value(
        camera,
        "camera_password",
        "",
    )

    rtsp_path = _camera_value(
        camera,
        "rtsp_path",
        "",
    )

    try:
        return build_camera_rtsp_url(
            camera_ip=camera_ip,
            camera_port=camera_port,
            camera_username=(
                camera_username
            ),
            camera_password=(
                camera_password
            ),
            rtsp_path=rtsp_path,
        )

    except CameraConfigError as error:
        raise ValueError(
            str(
                error
            )
        ) from error


def _open_rtsp_capture(
    rtsp_url: str,
):
    """
    Open RTSP using OpenCV timeout parameters
    when supported by the installed version.

    Older OpenCV versions fall back to the
    standard VideoCapture constructor.
    """
    timeout_parameters = [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
        RTSP_OPEN_TIMEOUT_MS,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC,
        RTSP_READ_TIMEOUT_MS,
    ]

    try:
        cap = cv2.VideoCapture(
            rtsp_url,
            cv2.CAP_FFMPEG,
            timeout_parameters,
        )

    except (
        TypeError,
        cv2.error,
    ):
        logger.debug(
            (
                "OpenCV timeout parameters "
                "are unavailable; using the "
                "standard RTSP capture"
            )
        )

        cap = cv2.VideoCapture(
            rtsp_url,
            cv2.CAP_FFMPEG,
        )

    try:
        cap.set(
            cv2.CAP_PROP_BUFFERSIZE,
            1,
        )

    except (
        AttributeError,
        cv2.error,
    ):
        logger.debug(
            (
                "OpenCV could not configure "
                "the RTSP buffer size"
            )
        )

    return cap


def _is_valid_frame(
    frame,
) -> bool:
    if frame is None:
        return False

    try:
        return (
            frame.size > 0
            and len(
                frame.shape
            ) >= 2
        )

    except (
        AttributeError,
        TypeError,
        ValueError,
    ):
        return False


def _read_valid_frame(
    cap,
) -> tuple[Any | None, int | None]:
    frame = None
    successful_attempt = None
    last_read_error = None

    for attempt in range(
        1,
        FRAME_READ_ATTEMPTS + 1,
    ):
        try:
            success, candidate = (
                cap.read()
            )

        except cv2.error as error:
            success = False
            candidate = None
            last_read_error = error

        except Exception as error:
            success = False
            candidate = None
            last_read_error = error

        if (
            success
            and _is_valid_frame(
                candidate
            )
        ):
            frame = candidate
            successful_attempt = attempt

            break

        if (
            attempt
            < FRAME_READ_ATTEMPTS
        ):
            time.sleep(
                FRAME_RETRY_DELAY_SECONDS
            )

    if (
        frame is None
        and last_read_error is not None
    ):
        logger.warning(
            (
                "RTSP frame reading failed: %s"
            ),
            last_read_error,
        )

    return (
        frame,
        successful_attempt,
    )


def _prepare_save_directory(
    captured_at: datetime,
) -> Path:
    date_folder = (
        captured_at.strftime(
            "%Y-%m-%d"
        )
    )

    save_dir = (
        RAW_IMAGES_DIR
        / date_folder
    )

    save_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return save_dir


def _build_image_paths(
    save_dir: Path,
    captured_at: datetime,
) -> tuple[Path, Path]:
    # ใช้ Microseconds ครบ 6 หลัก
    # เพื่อลดโอกาสชื่อไฟล์ซ้ำ
    filename_timestamp = (
        captured_at.strftime(
            "%Y-%m-%d_%H-%M-%S_%f"
        )
    )

    image_path = (
        save_dir
        / (
            f"{filename_timestamp}"
            "_rtsp.jpg"
        )
    )

    temporary_path = (
        save_dir
        / (
            f"{filename_timestamp}"
            "_rtsp.tmp.jpg"
        )
    )

    return (
        image_path,
        temporary_path,
    )


def _save_frame_atomically(
    frame,
    image_path: Path,
    temporary_path: Path,
) -> None:
    """
    Save to a temporary JPEG first and rename
    only after a valid non-empty file exists.
    """
    _safe_remove_file(
        temporary_path
    )

    try:
        saved = cv2.imwrite(
            str(
                temporary_path
            ),
            frame,
            [
                cv2.IMWRITE_JPEG_QUALITY,
                JPEG_QUALITY,
            ],
        )

    except cv2.error as error:
        raise OSError(
            (
                "OpenCV raised an error "
                "while saving the image"
            )
        ) from error

    if not saved:
        raise OSError(
            (
                "OpenCV could not save "
                "the image"
            )
        )

    try:
        file_size = (
            temporary_path.stat()
            .st_size
        )

    except OSError as error:
        raise OSError(
            (
                "Cannot verify the temporary "
                "image file"
            )
        ) from error

    if file_size <= 0:
        raise OSError(
            (
                "The temporary image file "
                "is empty"
            )
        )

    try:
        temporary_path.replace(
            image_path
        )

    except OSError as error:
        raise OSError(
            (
                "Cannot finalize the "
                "captured image file"
            )
        ) from error

    if not image_path.exists():
        raise OSError(
            (
                "The captured image file "
                "does not exist after saving"
            )
        )

    try:
        final_size = (
            image_path.stat()
            .st_size
        )

    except OSError as error:
        raise OSError(
            (
                "Cannot verify the final "
                "image file"
            )
        ) from error

    if final_size <= 0:
        raise OSError(
            (
                "The captured image file "
                "is empty"
            )
        )


def capture_rtsp_image():
    """
    Capture one valid frame from the active
    RTSP camera and save it under raw_images.

    The capture timestamp is recorded immediately
    after a valid frame is received, rather than
    when this function first starts.
    """
    try:
        camera = get_active_camera()

    except Exception:
        logger.exception(
            (
                "Cannot load active camera "
                "configuration"
            )
        )

        return _failure_result(
            stage="camera_config",
            message=(
                "Cannot load camera "
                "configuration."
            ),
        )

    if camera is None:
        logger.info(
            (
                "RTSP capture skipped because "
                "no active camera is configured"
            )
        )

        return _failure_result(
            stage="camera_config",
            message=(
                "Active camera configuration "
                "was not found."
            ),
        )

    camera_name = str(
        _camera_value(
            camera,
            "camera_name",
            "Unnamed camera",
        )
        or "Unnamed camera"
    ).strip()

    camera_ip = str(
        _camera_value(
            camera,
            "camera_ip",
            "",
        )
        or ""
    ).strip()

    camera_port = _camera_value(
        camera,
        "camera_port",
        554,
    )

    try:
        rtsp_url = build_rtsp_url(
            camera
        )

    except ValueError as error:
        logger.warning(
            (
                "Invalid RTSP camera "
                "configuration: "
                "camera=%s, ip=%s, "
                "port=%s, error=%s"
            ),
            camera_name,
            camera_ip,
            camera_port,
            error,
        )

        return _failure_result(
            stage="build_rtsp_url",
            message=(
                "Camera RTSP configuration "
                "is invalid."
            ),
        )

    logger.info(
        (
            "Starting RTSP capture: "
            "camera=%s, ip=%s, port=%s"
        ),
        camera_name,
        camera_ip,
        camera_port,
    )

    cap = None
    frame = None
    successful_attempt = None

    capture_started_at = (
        time.monotonic()
    )

    try:
        cap = _open_rtsp_capture(
            rtsp_url
        )

        if (
            cap is None
            or not cap.isOpened()
        ):
            logger.warning(
                (
                    "Cannot open RTSP stream: "
                    "camera=%s, ip=%s, "
                    "port=%s"
                ),
                camera_name,
                camera_ip,
                camera_port,
            )

            return _failure_result(
                stage="open_rtsp",
                message=(
                    "Cannot open RTSP stream."
                ),
            )

        (
            frame,
            successful_attempt,
        ) = _read_valid_frame(
            cap
        )

        if not _is_valid_frame(
            frame
        ):
            logger.warning(
                (
                    "RTSP stream opened but no "
                    "valid frame was received "
                    "after %d attempts: "
                    "camera=%s, ip=%s"
                ),
                FRAME_READ_ATTEMPTS,
                camera_name,
                camera_ip,
            )

            return _failure_result(
                stage="read_frame",
                message=(
                    "RTSP stream opened, "
                    "but no valid frame "
                    "was received."
                ),
            )

        # เวลานี้เป็นเวลาหลังได้รับ Frame
        # จึงใกล้เคียงเวลาจับภาพจริงที่สุด
        captured_at = (
            datetime.now()
            .astimezone()
        )

    except Exception:
        logger.exception(
            (
                "Unexpected RTSP capture "
                "error: camera=%s, ip=%s"
            ),
            camera_name,
            camera_ip,
        )

        return _failure_result(
            stage="rtsp_exception",
            message=(
                "An unexpected RTSP capture "
                "error occurred."
            ),
        )

    finally:
        _safe_release_capture(
            cap
        )

    elapsed_seconds = (
        time.monotonic()
        - capture_started_at
    )

    logger.info(
        (
            "RTSP frame received: "
            "camera=%s, attempt=%s, "
            "elapsed=%.2fs"
        ),
        camera_name,
        successful_attempt,
        elapsed_seconds,
    )

    try:
        save_dir = (
            _prepare_save_directory(
                captured_at
            )
        )

    except OSError:
        logger.exception(
            (
                "Cannot create raw image "
                "directory for capture time %s"
            ),
            captured_at.isoformat(),
        )

        return _failure_result(
            stage="create_directory",
            message=(
                "Cannot create the raw "
                "image directory."
            ),
        )

    (
        image_path,
        temporary_path,
    ) = _build_image_paths(
        save_dir=save_dir,
        captured_at=captured_at,
    )

    try:
        _save_frame_atomically(
            frame=frame,
            image_path=image_path,
            temporary_path=(
                temporary_path
            ),
        )

    except OSError as error:
        logger.exception(
            (
                "Cannot save RTSP image: "
                "camera=%s, image=%s, "
                "error=%s"
            ),
            camera_name,
            image_path,
            error,
        )

        _safe_remove_file(
            temporary_path
        )

        return _failure_result(
            stage="save_image",
            message=(
                "Cannot save the captured "
                "image."
            ),
        )

    finally:
        _safe_remove_file(
            temporary_path
        )

    capture_timestamp = int(
        captured_at.timestamp()
    )

    logger.info(
        (
            "RTSP image captured "
            "successfully: "
            "camera=%s, image=%s, "
            "capture_timestamp=%s"
        ),
        camera_name,
        image_path,
        capture_timestamp,
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
        ),
    }


if __name__ == "__main__":
    result = (
        capture_rtsp_image()
    )

    print(
        result
    )