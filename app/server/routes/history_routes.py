from flask import Blueprint, jsonify, request

from app.server.auth import require_api_key

from app.server.repositories.history_repository import (
    get_history_data,
    get_history_run_detail,
    get_history_runs,
    get_history_variables,
    get_latest_log
)

history_bp = Blueprint(
    "history",
    __name__
)


@history_bp.route("/api/latest")
@require_api_key
def api_latest():
    latest = get_latest_log()

    if latest is None:
        return jsonify({
            "ok": True,
            "has_data": False,
            "message": "No OCR data found",
            "data": None
        })

    return jsonify({
        "ok": True,
        "has_data": True,
        "data": latest
    })


@history_bp.route("/api/history")
@require_api_key
def api_history():
    runs = get_history_runs(limit=50)

    return jsonify({
        "ok": True,
        "count": len(runs),
        "items": runs
    })


@history_bp.route("/api/history/variables")
@require_api_key
def api_history_variables():
    variables = get_history_variables()

    return jsonify({
        "ok": True,
        "variables": variables
    })


@history_bp.route("/api/history/data")
@require_api_key
def api_history_data():
    tag_name = request.args.get("tag_name", "").strip()

    if tag_name == "":
        return jsonify({
            "ok": False,
            "message": "tag_name is required",
            "points": []
        })

    points = get_history_data(
        tag_name=tag_name,
        days=2
    )

    return jsonify({
        "ok": True,
        "tag_name": tag_name,
        "points": points
    })


@history_bp.route("/api/history/run/<int:run_id>")
@require_api_key
def api_history_run(run_id):
    detail = get_history_run_detail(run_id)

    if detail is None:
        return jsonify({
            "ok": False,
            "message": "Run not found"
        })

    return jsonify({
        "ok": True,
        "run": detail["run"],
        "values": detail["values"]
    })