import sqlite3
from collections.abc import Mapping

from flask import (
    Blueprint,
    jsonify,
    request,
)

from src.logger import create_logger
from src.server.auth import require_api_key
from src.server.repositories.tag_repository import (
    TagValidationError,
    save_user_tags_data,
)


logger = create_logger(
    "server.routes.tag"
)


tag_bp = Blueprint(
    "tag",
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


def _read_tags_payload():
    if not request.is_json:
        raise TagValidationError(
            (
                "Request body must use "
                "application/json"
            )
        )

    data = request.get_json(
        silent=True
    )

    if data is None:
        raise TagValidationError(
            (
                "Request body must contain "
                "valid JSON"
            )
        )

    if not isinstance(
        data,
        Mapping,
    ):
        raise TagValidationError(
            (
                "Request JSON must be "
                "an object"
            )
        )

    if "tags" not in data:
        raise TagValidationError(
            (
                "Request JSON must contain "
                "the tags field"
            )
        )

    tags = data.get(
        "tags"
    )

    if not isinstance(
        tags,
        list,
    ):
        raise TagValidationError(
            "Tags must be a list"
        )

    return tags


@tag_bp.route(
    "/api/save_user_tags",
    methods=["POST"],
)
@require_api_key
def api_save_user_tags():
    try:
        tags = (
            _read_tags_payload()
        )

        result = (
            save_user_tags_data(
                tags
            )
        )

        if not isinstance(
            result,
            Mapping,
        ):
            logger.error(
                (
                    "User-tag repository "
                    "returned an invalid result"
                )
            )

            return _error_response(
                (
                    "User-tag save returned "
                    "an invalid result"
                ),
                500,
            )

        if not result.get(
            "ok"
        ):
            message = str(
                result.get(
                    "message",
                    (
                        "User tags were "
                        "not saved"
                    ),
                )
            )

            logger.warning(
                (
                    "User tags were not "
                    "saved: %s"
                ),
                message,
            )

            return jsonify(
                dict(
                    result
                )
            ), 400

        logger.info(
            (
                "User tags saved through "
                "API: count=%d"
            ),
            len(
                result.get(
                    "tags",
                    [],
                )
            ),
        )

        return jsonify(
            dict(
                result
            )
        )

    except TagValidationError as error:
        logger.warning(
            (
                "User-tag save rejected: %s"
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
        ).lower()

        if "locked" in error_text:
            logger.warning(
                (
                    "User-tag database is "
                    "temporarily locked"
                )
            )

            return _error_response(
                (
                    "User-tag database is "
                    "temporarily busy. "
                    "Please try again."
                ),
                503,
            )

        logger.exception(
            (
                "Database operation failed "
                "while saving user tags"
            )
        )

        return _error_response(
            (
                "Failed to save user tags "
                "to the database"
            ),
            500,
        )

    except sqlite3.Error:
        logger.exception(
            (
                "Database error while "
                "saving user tags"
            )
        )

        return _error_response(
            (
                "Failed to save user tags "
                "to the database"
            ),
            500,
        )

    except Exception:
        logger.exception(
            (
                "Unexpected error while "
                "saving user tags"
            )
        )

        return _error_response(
            "Failed to save user tags",
            500,
        )