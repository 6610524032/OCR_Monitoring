from flask import Blueprint, jsonify, request

from src.logger import create_logger
from src.server.auth import require_api_key
from src.server.repositories.tag_repository import (
    save_user_tags_data
)


logger = create_logger(
    "server.routes.tag"
)


tag_bp = Blueprint(
    "tag",
    __name__
)


@tag_bp.route(
    "/api/save_user_tags",
    methods=["POST"]
)
@require_api_key
def api_save_user_tags():
    try:
        data = request.json or {}

        tags = data.get(
            "tags",
            []
        )

        result = save_user_tags_data(
            tags
        )

        if result.get("ok"):
            logger.info(
                "User tags saved successfully"
            )
        else:
            logger.warning(
                "User tags were not saved: %s",
                result.get(
                    "message",
                    "Unknown error"
                )
            )

        return jsonify(result)

    except Exception:
        logger.exception(
            "Failed to save user tags"
        )

        return jsonify({
            "ok": False,
            "message": "Failed to save user tags"
        }), 500