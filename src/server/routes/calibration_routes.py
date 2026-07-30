import sqlite3
from collections.abc import Mapping

from flask import (
    Blueprint,
    jsonify,
    request,
)

from src.logger import create_logger
from src.processing.calibration import (
    create_calibration_preview,
    get_latest_file,
)
from src.server.auth import require_api_key
from src.server.config import (
    CALIBRATED_IMAGES_DIR,
    RAW_IMAGES_DIR,
)
from src.server.repositories.calibration_repository import (
    CalibrationValidationError,
    get_active_calibration,
    save_calibration_data,
)
from src.server.repositories.tag_repository import (
    get_user_tags_for_settings,
)


logger = create_logger(
    "server.routes.calibration"
)


calibration_bp = Blueprint(
    "calibration",
    __name__,
)


def _error_response(
    message: str,
    status_code: int,
):
    return jsonify({
        "ok": False,
        "message": message,
    }), status_code


def _read_json_object():
    if not request.is_json:
        raise CalibrationValidationError(
            (
                "Request body must use "
                "application/json"
            )
        )

    data = request.get_json(
        silent=True
    )

    if data is None:
        raise CalibrationValidationError(
            (
                "Request body must contain "
                "valid JSON"
            )
        )

    if not isinstance(
        data,
        Mapping,
    ):
        raise CalibrationValidationError(
            (
                "Request JSON must be "
                "an object"
            )
        )

    return data


def _preview_failure_status(
    message: str,
) -> int:
    normalized_message = (
        str(
            message
            or ""
        )
        .strip()
        .lower()
    )

    if normalized_message in {
        "no raw image found",
        "no active calibration found",
    }:
        return 404

    if (
        normalized_message.startswith(
            "cannot read raw image"
        )
        or normalized_message.startswith(
            "cannot apply calibration"
        )
    ):
        return 422

    if (
        normalized_message.startswith(
            "cannot save calibrated image"
        )
        or normalized_message.startswith(
            "invalid calibrated image path"
        )
    ):
        return 500

    return 400


@calibration_bp.route(
    "/api/save_calibration",
    methods=["POST"],
)
@require_api_key
def api_save_calibration():
    try:
        data = _read_json_object()

        saved_calibration = (
            save_calibration_data(
                data
            )
        )

        logger.info(
            (
                "Calibration saved through "
                "API: id=%s"
            ),
            saved_calibration.get(
                "id"
            ),
        )

        return jsonify({
            "ok": True,
            "calibration": (
                saved_calibration
            ),
        })

    except CalibrationValidationError as error:
        logger.warning(
            (
                "Calibration save rejected: "
                "%s"
            ),
            error,
        )

        return _error_response(
            str(
                error
            ),
            400,
        )

    except sqlite3.OperationalError as error:
        error_text = str(
            error
        )

        if "locked" in error_text.lower():
            logger.warning(
                (
                    "Calibration database "
                    "is temporarily locked"
                )
            )

            return _error_response(
                (
                    "Calibration database is "
                    "temporarily busy. "
                    "Please try again."
                ),
                503,
            )

        logger.exception(
            (
                "Database operation failed "
                "while saving calibration"
            )
        )

        return _error_response(
            (
                "Failed to save calibration "
                "to the database"
            ),
            500,
        )

    except sqlite3.Error:
        logger.exception(
            (
                "Database error while "
                "saving calibration"
            )
        )

        return _error_response(
            (
                "Failed to save calibration "
                "to the database"
            ),
            500,
        )

    except Exception:
        logger.exception(
            (
                "Unexpected error while "
                "saving calibration"
            )
        )

        return _error_response(
            "Failed to save calibration",
            500,
        )


@calibration_bp.route(
    "/api/test_calibration",
    methods=["POST"],
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

        if not isinstance(
            result,
            Mapping,
        ):
            logger.error(
                (
                    "Calibration preview "
                    "returned an invalid result"
                )
            )

            return _error_response(
                (
                    "Calibration preview "
                    "returned an invalid result"
                ),
                500,
            )

        if result.get(
            "ok"
        ):
            logger.info(
                (
                    "Calibration preview "
                    "created successfully"
                )
            )

            return jsonify(
                dict(
                    result
                )
            )

        message = str(
            result.get(
                "message",
                (
                    "Cannot create "
                    "calibration preview"
                ),
            )
        )

        status_code = (
            _preview_failure_status(
                message
            )
        )

        if status_code >= 500:
            logger.error(
                (
                    "Calibration preview "
                    "failed: %s"
                ),
                message,
            )

        else:
            logger.warning(
                (
                    "Calibration preview "
                    "was not created: %s"
                ),
                message,
            )

        return jsonify(
            dict(
                result
            )
        ), status_code

    except sqlite3.OperationalError as error:
        if "locked" in str(
            error
        ).lower():
            logger.warning(
                (
                    "Calibration database "
                    "is temporarily locked"
                )
            )

            return _error_response(
                (
                    "Calibration database is "
                    "temporarily busy. "
                    "Please try again."
                ),
                503,
            )

        logger.exception(
            (
                "Database operation failed "
                "while creating calibration "
                "preview"
            )
        )

        return _error_response(
            (
                "Failed to load calibration "
                "from the database"
            ),
            500,
        )

    except sqlite3.Error:
        logger.exception(
            (
                "Database error while "
                "creating calibration preview"
            )
        )

        return _error_response(
            (
                "Failed to load calibration "
                "from the database"
            ),
            500,
        )

    except Exception:
        logger.exception(
            (
                "Unexpected error while "
                "creating calibration preview"
            )
        )

        return _error_response(
            (
                "Failed to create "
                "calibration preview"
            ),
            500,
        )


@calibration_bp.route(
    "/api/latest_calibrated_image",
    methods=["GET"],
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
            logger.debug(
                (
                    "No calibrated image "
                    "found"
                )
            )

            return jsonify({
                "ok": False,
                "image": None,
                "image_url": None,
            })

        return jsonify({
            "ok": True,
            "image": (
                latest_calibrated_image
            ),
            "image_url": (
                "/calibrated_images/"
                + latest_calibrated_image
            ),
        })

    except Exception:
        logger.exception(
            (
                "Failed to load latest "
                "calibrated image"
            )
        )

        return _error_response(
            (
                "Failed to load latest "
                "calibrated image"
            ),
            500,
        )


@calibration_bp.route(
    "/api/latest_raw_image",
    methods=["GET"],
)
@require_api_key
def api_latest_raw_image():
    try:
        latest_image = (
            get_latest_file(
                RAW_IMAGES_DIR
            )
        )

        if latest_image is None:
            logger.debug(
                "No raw image found"
            )

            return jsonify({
                "ok": False,
                "image": None,
                "image_url": None,
            })

        return jsonify({
            "ok": True,
            "image": latest_image,
            "image_url": (
                "/raw_images/"
                + latest_image
            ),
        })

    except Exception:
        logger.exception(
            (
                "Failed to load latest "
                "raw image"
            )
        )

        return _error_response(
            (
                "Failed to load latest "
                "raw image"
            ),
            500,
        )


@calibration_bp.route(
    "/api/settings/bootstrap",
    methods=["GET"],
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

        if user_tags is None:
            user_tags = []

        if not isinstance(
            user_tags,
            list,
        ):
            user_tags = list(
                user_tags
            )

        logger.debug(
            (
                "Settings bootstrap "
                "loaded successfully"
            )
        )

        return jsonify({
            "ok": True,
            "calibration": calibration,
            "user_tags": user_tags,
        })

    except sqlite3.OperationalError as error:
        if "locked" in str(
            error
        ).lower():
            logger.warning(
                (
                    "Settings database is "
                    "temporarily locked"
                )
            )

            return _error_response(
                (
                    "Settings database is "
                    "temporarily busy. "
                    "Please try again."
                ),
                503,
            )

        logger.exception(
            (
                "Database operation failed "
                "while loading settings"
            )
        )

        return _error_response(
            (
                "Failed to load settings "
                "from the database"
            ),
            500,
        )

    except sqlite3.Error:
        logger.exception(
            (
                "Database error while "
                "loading settings bootstrap"
            )
        )

        return _error_response(
            (
                "Failed to load settings "
                "from the database"
            ),
            500,
        )

    except Exception:
        logger.exception(
            (
                "Unexpected error while "
                "loading settings bootstrap"
            )
        )

        return _error_response(
            "Failed to load settings",
            500,
        )