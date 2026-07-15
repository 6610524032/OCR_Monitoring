from flask import Blueprint, jsonify, request

from app.processing.calibration import (
    create_calibration_preview,
    get_latest_file
)

from app.server.auth import require_api_key

from app.server.config import (
    CALIBRATED_IMAGES_DIR,
    RAW_IMAGES_DIR
)

from app.server.repositories.calibration_repository import (
    get_active_calibration,
    save_calibration_data
)

from app.server.repositories.tag_repository import (
    get_user_tags_for_settings
)

calibration_bp = Blueprint(
    "calibration",
    __name__
)


@calibration_bp.route("/api/save_calibration", methods=["POST"])
@require_api_key
def api_save_calibration():
    data = request.json or {}

    save_calibration_data(data)

    return jsonify({
        "ok": True
    })


@calibration_bp.route("/api/test_calibration", methods=["POST"])
@require_api_key
def api_test_calibration():
    calibration = get_active_calibration()

    result = create_calibration_preview(
        calibration=calibration
    )

    return jsonify(result)


@calibration_bp.route("/api/latest_calibrated_image")
@require_api_key
def api_latest_calibrated_image():
    latest_calibrated_image = get_latest_file(
        CALIBRATED_IMAGES_DIR
    )

    if latest_calibrated_image is None:
        return jsonify({
            "ok": False,
            "image": None
        })

    return jsonify({
        "ok": True,
        "image": latest_calibrated_image,
        "image_url": "/calibrated_images/" + latest_calibrated_image
    })


@calibration_bp.route("/api/latest_raw_image")
@require_api_key
def api_latest_raw_image():
    latest_image = get_latest_file(RAW_IMAGES_DIR)

    if latest_image is None:
        return jsonify({
            "ok": False,
            "image": None
        })

    return jsonify({
        "ok": True,
        "image": latest_image,
        "image_url": "/raw_images/" + latest_image
    })


@calibration_bp.route("/api/settings/bootstrap")
@require_api_key
def api_settings_bootstrap():
    calibration = get_active_calibration()
    user_tags = get_user_tags_for_settings()

    return jsonify({
        "ok": True,
        "calibration": calibration,
        "user_tags": user_tags
    })