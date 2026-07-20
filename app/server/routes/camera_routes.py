from flask import Blueprint, jsonify, request

from app.server.auth import require_api_key
from app.server.repositories.camera_repository import (
    get_active_camera,
    save_camera_config
)


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