from flask import Blueprint, jsonify, request

from src.logger import create_logger

from src.processing.calibration import (
    create_calibration_preview,
    get_latest_file
)

from src.server.auth import require_api_key

from src.server.config import (
    CALIBRATED_IMAGES_DIR,
    RAW_IMAGES_DIR
)

from src.server.repositories.calibration_repository import (
    get_active_calibration,
    save_calibration_data
)

from src.server.repositories.tag_repository import (
    get_user_tags_for_settings
)


logger = create_logger(
    "server.routes.calibration"
)


calibration_bp = Blueprint(
    "calibration",
    __name__
)


@calibration_bp.route(
    "/api/save_calibration",
    methods=["POST"]
)
@require_api_key
def api_save_calibration():
    data = request.json or {}

    try:
        save_calibration_data(data)

        logger.info(
            "Calibration saved successfully"
        )

        return jsonify({
            "ok": True
        })

    except Exception:
        logger.exception(
            "Failed to save calibration"
        )

        return jsonify({
            "ok": False,
            "message": "Failed to save calibration"
        }), 500


@calibration_bp.route(
    "/api/test_calibration",
    methods=["POST"]
)
@require_api_key
def api_test_calibration():
    try:
        calibration = (
            get_active_calibration()
        )

        result = (
            create_calibration_preview(
                calibration=calibration
            )
        )

        logger.info(
            "Calibration preview created"
        )

        return jsonify(result)

    except Exception:
        logger.exception(
            "Failed to create calibration preview"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Failed to create calibration preview"
            )
        }), 500


@calibration_bp.route(
    "/api/latest_calibrated_image"
)
@require_api_key
def api_latest_calibrated_image():
    try:
        latest_calibrated_image = (
            get_latest_file(
                CALIBRATED_IMAGES_DIR
            )
        )

        if latest_calibrated_image is None:
            logger.info(
                "No calibrated image found"
            )

            return jsonify({
                "ok": False,
                "image": None
            })

        return jsonify({
            "ok": True,
            "image": latest_calibrated_image,
            "image_url":
                "/calibrated_images/"
                + latest_calibrated_image
        })

    except Exception:
        logger.exception(
            "Failed to load latest calibrated image"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Failed to load latest calibrated image"
            )
        }), 500


@calibration_bp.route(
    "/api/latest_raw_image"
)
@require_api_key
def api_latest_raw_image():
    try:
        latest_image = get_latest_file(
            RAW_IMAGES_DIR
        )

        if latest_image is None:
            logger.info(
                "No raw image found"
            )

            return jsonify({
                "ok": False,
                "image": None
            })

        return jsonify({
            "ok": True,
            "image": latest_image,
            "image_url":
                "/raw_images/"
                + latest_image
        })

    except Exception:
        logger.exception(
            "Failed to load latest raw image"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Failed to load latest raw image"
            )
        }), 500


@calibration_bp.route(
    "/api/settings/bootstrap"
)
@require_api_key
def api_settings_bootstrap():
    try:
        calibration = (
            get_active_calibration()
        )

        user_tags = (
            get_user_tags_for_settings()
        )

        logger.info(
            "Settings bootstrap loaded"
        )

        return jsonify({
            "ok": True,
            "calibration": calibration,
            "user_tags": user_tags
        })

    except Exception:
        logger.exception(
            "Failed to load settings bootstrap"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Failed to load settings"
            )
        }), 500