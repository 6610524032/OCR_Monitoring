from flask import Blueprint, jsonify

from app.server.auth import require_api_key
from app.server.repositories.camera_repository import (
    get_active_camera
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
            "camera_username": camera["camera_username"],
            "camera_password": camera["camera_password"],
            "rtsp_path": camera["rtsp_path"]
        }
    })