from flask import Blueprint, jsonify, request

from app.server.auth import require_api_key

from app.server.repositories.tag_repository import (
    save_user_tags_data
)

tag_bp = Blueprint(
    "tag",
    __name__
)


@tag_bp.route("/api/save_user_tags", methods=["POST"])
@require_api_key
def api_save_user_tags():
    data = request.json or {}
    tags = data.get("tags", [])

    result = save_user_tags_data(tags)

    return jsonify(result)