from flask import Blueprint, jsonify, request
import cv2
from urllib.parse import quote
from app.server.auth import require_api_key
from app.server.repositories.camera_repository import (
    get_active_camera,
    save_camera_config
)
from pathlib import Path

from app.processing.rtsp_capture import (
    capture_rtsp_image
)

from app.server.config import RAW_IMAGES_DIR
camera_bp = Blueprint(
    "camera",
    __name__
)


@camera_bp.route("/api/camera/config", methods=["GET"])
@require_api_key
def api_camera_config():

    camera = get_active_camera()

    if camera is None:
        return jsonify({
            "ok": False,
            "message": "Camera configuration not found"
        }), 404

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


@camera_bp.route("/api/camera/config", methods=["POST"])
@require_api_key
def api_save_camera_config():

    data = request.get_json(silent=True) or {}

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
        if str(data.get(field, "")).strip() == ""
    ]

    if missing_fields:
        return jsonify({
            "ok": False,
            "message": (
                "Missing required fields: "
                + ", ".join(missing_fields)
            )
        }), 400

    camera_data = {

        "camera_name": str(
            data["camera_name"]
        ).strip(),

        "camera_ip": str(
            data["camera_ip"]
        ).strip(),

        "camera_port": int(
            data["camera_port"]
        ),

        "camera_username": str(
            data["camera_username"]
        ).strip(),

        "camera_password": str(
            data["camera_password"]
        ),

        "rtsp_path": str(
            data["rtsp_path"]
        ).strip()

    }

    try:

        save_camera_config(camera_data)

    except Exception as error:

        print(
            "Save camera configuration error:",
            error
        )

        return jsonify({
            "ok": False,
            "message": "Cannot save camera configuration"
        }), 500

    return jsonify({
        "ok": True,
        "message": "Camera configuration saved"
    })

@camera_bp.route("/api/camera/test", methods=["POST"])
@require_api_key
def api_test_camera():

    data = request.get_json(silent=True) or {}

    try:
        camera_ip = str(data.get("camera_ip", "")).strip()
        camera_port = int(data.get("camera_port", 554))
        camera_username = str(data.get("camera_username", "")).strip()
        camera_password = str(data.get("camera_password", "")).strip()
        rtsp_path = str(data.get("rtsp_path", "")).strip()

        if not rtsp_path.startswith("/"):
            rtsp_path = "/" + rtsp_path

        username = quote(camera_username, safe="")
        password = quote(camera_password, safe="")

        rtsp_url = (
            f"rtsp://{username}:{password}"
            f"@{camera_ip}:{camera_port}{rtsp_path}"
        )

        cap = cv2.VideoCapture(rtsp_url)

        ok, _ = cap.read()

        cap.release()

        if ok:
            return jsonify({
                "ok": True,
                "message": "Camera connected successfully."
            })

        return jsonify({
            "ok": False,
            "message": "Cannot connect to camera."
        })

    except Exception as error:

        print("Camera test error:", error)

        return jsonify({
            "ok": False,
            "message": str(error)
        }), 500


@camera_bp.route("/api/capture_image", methods=["POST"])
@require_api_key
def api_capture_image():

    try:
        capture_result = capture_rtsp_image()

        if capture_result is None:
            return jsonify({
                "ok": False,
                "message": "Cannot capture image."
            }), 500

        image_path = capture_result.get("image_path")
        captured_at = capture_result.get("captured_at")
        capture_timestamp = capture_result.get(
            "capture_timestamp"
        )

        if not image_path:
            return jsonify({
                "ok": False,
                "message": (
                    "Capture result does not contain "
                    "an image path."
                )
            }), 500

        image_path_obj = Path(image_path).resolve()

        if not image_path_obj.exists():
            return jsonify({
                "ok": False,
                "message": (
                    "Captured image file does not exist: "
                    + str(image_path_obj)
                )
            }), 500

        raw_images_dir = Path(
            RAW_IMAGES_DIR
        ).resolve()

        try:
            relative_image_path = (
                image_path_obj
                .relative_to(raw_images_dir)
                .as_posix()
            )

        except ValueError:
            date_folder = image_path_obj.parent.name

            relative_image_path = (
                date_folder
                + "/"
                + image_path_obj.name
            )

        image_url = (
            "/raw_images/"
            + relative_image_path
        )

        print(
            "Captured image path:",
            image_path_obj
        )

        print(
            "Captured image URL:",
            image_url
        )

        return jsonify({
            "ok": True,
            "image": relative_image_path,
            "image_url": image_url,
            "captured_at": captured_at,
            "capture_timestamp": capture_timestamp,
            "message": "Image captured successfully."
        })

    except Exception as error:

        print(
            "Capture image error:",
            error
        )

        return jsonify({
            "ok": False,
            "message": str(error)
        }), 500