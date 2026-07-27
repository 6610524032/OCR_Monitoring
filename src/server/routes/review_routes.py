from flask import Blueprint, jsonify, request

from src.logger import create_logger
from src.server.auth import require_api_key
from src.server.repositories.review_repository import (
    accept_review_run,
    delete_review_run,
    get_review_count,
    get_review_list,
    save_review_values
)


logger = create_logger(
    "server.routes.review"
)


review_bp = Blueprint(
    "review",
    __name__
)


@review_bp.route("/api/review/count")
@require_api_key
def api_review_count():
    try:
        total = get_review_count()

        logger.info(
            "Review count loaded (%d)",
            total
        )

        return jsonify({
            "ok": True,
            "count": total
        })

    except Exception:
        logger.exception(
            "Failed to load review count"
        )

        return jsonify({
            "ok": False,
            "message": "Failed to load review count"
        }), 500


@review_bp.route("/api/review/list")
@require_api_key
def api_review_list():
    try:
        items = get_review_list()

        logger.info(
            "Review list loaded (%d item(s))",
            len(items)
        )

        return jsonify({
            "ok": True,
            "items": items
        })

    except Exception:
        logger.exception(
            "Failed to load review list"
        )

        return jsonify({
            "ok": False,
            "message": "Failed to load review list"
        }), 500


@review_bp.route(
    "/api/review/accept/<int:run_id>",
    methods=["POST"]
)
@require_api_key
def api_review_accept(run_id):
    try:
        accepted = accept_review_run(
            run_id
        )

        if accepted is False:
            logger.info(
                "Review run %s not found",
                run_id
            )

            return jsonify({
                "ok": False,
                "message": "Run not found"
            }), 404

        logger.info(
            "Review run %s accepted",
            run_id
        )

        return jsonify({
            "ok": True,
            "message": "Run accepted"
        })

    except Exception:
        logger.exception(
            "Failed to accept review run %s",
            run_id
        )

        return jsonify({
            "ok": False,
            "message": "Failed to accept review run"
        }), 500


@review_bp.route(
    "/api/review/delete/<int:run_id>",
    methods=["POST"]
)
@require_api_key
def api_review_delete(run_id):
    try:
        deleted = delete_review_run(
            run_id
        )

        if not deleted:
            logger.info(
                "Review run %s not found",
                run_id
            )

            return jsonify({
                "ok": False,
                "message": "Run not found"
            }), 404

        logger.info(
            "Review run %s deleted",
            run_id
        )

        return jsonify({
            "ok": True,
            "message": "Run deleted"
        })

    except Exception:
        logger.exception(
            "Failed to delete review run %s",
            run_id
        )

        return jsonify({
            "ok": False,
            "message": "Failed to delete review run"
        }), 500


@review_bp.route(
    "/api/review/save_values/<int:run_id>",
    methods=["POST"]
)
@require_api_key
def api_review_save_values(run_id):
    try:
        data = request.json or {}

        values = data.get(
            "values",
            []
        )

        result = save_review_values(
            run_id=run_id,
            values=values
        )

        logger.info(
            "Review values saved for run %s",
            run_id
        )

        return jsonify(result)

    except Exception:
        logger.exception(
            "Failed to save review values for run %s",
            run_id
        )

        return jsonify({
            "ok": False,
            "message": "Failed to save review values"
        }), 500