from pathlib import Path
from urllib.parse import quote

import cv2
from flask import Blueprint, jsonify, request

from src.logger import create_logger
from src.processing.rtsp_capture import (
    capture_rtsp_image
)
from src.server.auth import require_api_key
from src.server.config import RAW_IMAGES_DIR
from src.server.repositories.camera_repository import (
    get_active_camera,
    save_camera_config
)


logger = create_logger(
    "server.routes.camera"
)


camera_bp = Blueprint(
    "camera",
    __name__
)


@camera_bp.route(
    "/api/camera/config",
    methods=["GET"]
)
@require_api_key
def api_camera_config():
    try:
        camera = get_active_camera()

        if camera is None:
            logger.info(
                "Camera configuration not found"
            )

            return jsonify({
                "ok": False,
                "configured": False,
                "camera": None,
                "message": (
                    "Camera configuration not found"
            )
        })

        logger.info(
            "Camera configuration loaded"
        )

        return jsonify({
            "ok": True,
            "camera": {
                "camera_name": camera["camera_name"],
                "camera_ip": camera["camera_ip"],
                "camera_port": camera["camera_port"],
                "camera_username": camera["camera_username"],
                "camera_password": camera["camera_password"],
                "rtsp_path": camera["rtsp_path"]
            }
        })

    except Exception:
        logger.exception(
            "Failed to load camera configuration"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Failed to load camera configuration"
            )
        }), 500


@camera_bp.route(
    "/api/camera/config",
    methods=["POST"]
)
@require_api_key
def api_save_camera_config():
    try:
        data = request.get_json(
            silent=True
        ) or {}

        required_fields = [
            "camera_name",
            "camera_ip",
            "camera_port",
            "camera_username",
            "camera_password",
            "rtsp_path"
        ]

        missing_fields = [
            field
            for field in required_fields
            if str(
                data.get(field, "")
            ).strip() == ""
        ]

        if missing_fields:
            logger.warning(
                (
                    "Camera configuration "
                    "is incomplete: %s"
                ),
                ", ".join(
                    missing_fields
                )
            )

            return jsonify({
                "ok": False,
                "message": (
                    "Missing required fields: "
                    + ", ".join(
                        missing_fields
                    )
                )
            }), 400

        try:
            camera_port = int(
                data.get(
                    "camera_port"
                )
            )

        except (
            TypeError,
            ValueError
        ):
            logger.warning(
                "Camera port is invalid"
            )

            return jsonify({
                "ok": False,
                "message": (
                    "Camera port must be "
                    "a valid number."
                )
            }), 400

        if not (
            1 <= camera_port <= 65535
        ):
            logger.warning(
                (
                    "Camera port is outside "
                    "the valid range: %s"
                ),
                camera_port
            )

            return jsonify({
                "ok": False,
                "message": (
                    "Camera port must be "
                    "between 1 and 65535."
                )
            }), 400

        rtsp_path = str(
            data.get(
                "rtsp_path",
                ""
            )
        ).strip()

        if not rtsp_path.startswith("/"):
            rtsp_path = (
                "/"
                + rtsp_path
            )

        camera_data = {
            "camera_name": str(
                data.get(
                    "camera_name",
                    ""
                )
            ).strip(),

            "camera_ip": str(
                data.get(
                    "camera_ip",
                    ""
                )
            ).strip(),

            "camera_port": (
                camera_port
            ),

            "camera_username": str(
                data.get(
                    "camera_username",
                    ""
                )
            ).strip(),

            "camera_password": str(
                data.get(
                    "camera_password",
                    ""
                )
            ),

            "rtsp_path": rtsp_path
        }

        save_camera_config(
            camera_data
        )

        logger.info(
            "Camera configuration saved"
        )

        return jsonify({
            "ok": True,
            "message": (
                "Camera configuration saved"
            )
        })

    except Exception:
        logger.exception(
            "Failed to save camera configuration"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Cannot save camera configuration"
            )
        }), 500


@camera_bp.route(
    "/api/camera/test",
    methods=["POST"]
)
@require_api_key
def api_test_camera():
    cap = None

    try:
        data = request.get_json(
            silent=True
        ) or {}

        camera_ip = str(
            data.get(
                "camera_ip",
                ""
            )
        ).strip()

        camera_username = str(
            data.get(
                "camera_username",
                ""
            )
        ).strip()

        camera_password = str(
            data.get(
                "camera_password",
                ""
            )
        )

        rtsp_path = str(
            data.get(
                "rtsp_path",
                ""
            )
        ).strip()

        if not camera_ip:
            return jsonify({
                "ok": False,
                "message": (
                    "Camera IP is required."
                )
            }), 400

        try:
            camera_port = int(
                data.get(
                    "camera_port",
                    554
                )
            )

        except (
            TypeError,
            ValueError
        ):
            return jsonify({
                "ok": False,
                "message": (
                    "Camera port must be "
                    "a valid number."
                )
            }), 400

        if not (
            1 <= camera_port <= 65535
        ):
            return jsonify({
                "ok": False,
                "message": (
                    "Camera port must be "
                    "between 1 and 65535."
                )
            }), 400

        if not rtsp_path:
            return jsonify({
                "ok": False,
                "message": (
                    "RTSP path is required."
                )
            }), 400

        if not rtsp_path.startswith("/"):
            rtsp_path = (
                "/"
                + rtsp_path
            )

        username = quote(
            camera_username,
            safe=""
        )

        password = quote(
            camera_password,
            safe=""
        )

        rtsp_url = (
            f"rtsp://{username}:{password}"
            f"@{camera_ip}:{camera_port}"
            f"{rtsp_path}"
        )

        cap = cv2.VideoCapture(
            rtsp_url,
            cv2.CAP_FFMPEG
        )

        if not cap.isOpened():
            logger.warning(
                "Camera connection could not be opened"
            )

            return jsonify({
                "ok": False,
                "message": (
                    "Cannot connect to camera."
                )
            })

        ok, _ = cap.read()

        if not ok:
            logger.warning(
                "Camera opened but no frame was received"
            )

            return jsonify({
                "ok": False,
                "message": (
                    "Camera connected, but "
                    "no image was received."
                )
            })

        logger.info(
            "Camera connection test succeeded"
        )

        return jsonify({
            "ok": True,
            "message": (
                "Camera connected successfully."
            )
        })

    except Exception:
        logger.exception(
            "Camera connection test failed"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Camera connection test failed"
            )
        }), 500

    finally:
        if cap is not None:
            cap.release()


@camera_bp.route(
    "/api/capture_image",
    methods=["POST"]
)
@require_api_key
def api_capture_image():
    try:
        capture_result = (
            capture_rtsp_image()
        )

        if capture_result is None:
            logger.error(
                "Capture returned no result"
            )

            return jsonify({
                "ok": False,
                "message": (
                    "Cannot capture image."
                )
            }), 500

        if not isinstance(
            capture_result,
            dict
        ):
            logger.error(
                (
                    "Capture returned invalid "
                    "result data: %r"
                ),
                capture_result
            )

            return jsonify({
                "ok": False,
                "stage": "capture_result",
                "message": (
                    "Capture returned an "
                    "invalid result."
                )
            }), 500

        if not capture_result.get("ok"):
            logger.warning(
                "Capture failed at stage '%s'",
                capture_result.get(
                    "stage",
                    "unknown"
                )
            )

            return jsonify({
                "ok": False,
                "stage": capture_result.get(
                    "stage",
                    "unknown"
                ),
                "message": capture_result.get(
                    "message",
                    "Cannot capture image."
                )
            }), 500

        image_path = capture_result.get(
            "image_path"
        )

        captured_at = capture_result.get(
            "captured_at"
        )

        capture_timestamp = capture_result.get(
            "capture_timestamp"
        )

        if not image_path:
            logger.error(
                "Capture result does not contain image path"
            )

            return jsonify({
                "ok": False,
                "stage": "capture_result",
                "message": (
                    "Capture succeeded but the result "
                    "does not contain an image path."
                )
            }), 500

        image_path_obj = Path(
            image_path
        ).resolve()

        if not image_path_obj.exists():
            logger.error(
                "Captured image file does not exist"
            )

            return jsonify({
                "ok": False,
                "stage": "verify_image",
                "message": (
                    "Captured image file does not exist."
                )
            }), 500

        raw_images_dir = Path(
            RAW_IMAGES_DIR
        ).resolve()

        try:
            relative_image_path = (
                image_path_obj
                .relative_to(
                    raw_images_dir
                )
                .as_posix()
            )

        except ValueError:
            relative_image_path = (
                image_path_obj.parent.name
                + "/"
                + image_path_obj.name
            )

        logger.info(
            "Image captured successfully"
        )

        return jsonify({
            "ok": True,
            "image": relative_image_path,
            "image_url": (
                "/raw_images/"
                + relative_image_path
            ),
            "captured_at": captured_at,
            "capture_timestamp": capture_timestamp,
            "message": (
                "Image captured successfully."
            )
        })

    except Exception:
        logger.exception(
            "Unexpected capture route error"
        )

        return jsonify({
            "ok": False,
            "stage": "capture_route",
            "message": (
                "Unexpected server error"
            )
        }), 500