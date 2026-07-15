from flask import Blueprint, jsonify, request

from app.server.auth import require_api_key

from app.server.repositories.review_repository import (
    accept_review_run,
    delete_review_run,
    get_review_count,
    get_review_list,
    save_review_values
)

review_bp = Blueprint(
    "review",
    __name__
)


@review_bp.route("/api/review/count")
@require_api_key
def api_review_count():
    total = get_review_count()

    return jsonify({
        "ok": True,
        "count": total
    })


@review_bp.route("/api/review/list")
@require_api_key
def api_review_list():
    items = get_review_list()

    return jsonify({
        "ok": True,
        "items": items
    })


@review_bp.route("/api/review/accept/<int:run_id>", methods=["POST"])
@require_api_key
def api_review_accept(run_id):
    accept_review_run(run_id)

    return jsonify({
        "ok": True,
        "message": "Run accepted"
    })


@review_bp.route("/api/review/delete/<int:run_id>", methods=["POST"])
@require_api_key
def api_review_delete(run_id):
    deleted = delete_review_run(run_id)

    if not deleted:
        return jsonify({
            "ok": False,
            "message": "Run not found"
        })

    return jsonify({
        "ok": True,
        "message": "Run deleted"
    })


@review_bp.route("/api/review/save_values/<int:run_id>", methods=["POST"])
@require_api_key
def api_review_save_values(run_id):
    data = request.json or {}
    values = data.get("values", [])

    result = save_review_values(
        run_id=run_id,
        values=values
    )

    return jsonify(result)