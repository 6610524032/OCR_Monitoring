from flask import Blueprint, jsonify, request

from src.logger import create_logger
from src.server.auth import require_api_key
from src.server.repositories.history_repository import (
    get_history_data,
    get_history_run_detail,
    get_history_runs,
    get_history_variables,
    get_latest_log
)


logger = create_logger(
    "server.routes.history"
)


history_bp = Blueprint(
    "history",
    __name__
)


@history_bp.route("/api/latest")
@require_api_key
def api_latest():
    try:
        latest = get_latest_log()

        if latest is None:
            logger.info(
                "No latest OCR data available"
            )

            return jsonify({
                "ok": True,
                "has_data": False,
                "message": "No OCR data found",
                "data": None
            })

        logger.info(
            "Latest OCR data loaded"
        )

        return jsonify({
            "ok": True,
            "has_data": True,
            "data": latest
        })

    except Exception:
        logger.exception(
            "Failed to load latest OCR data"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Failed to load latest OCR data"
            )
        }), 500


@history_bp.route("/api/history")
@require_api_key
def api_history():
    try:
        runs = get_history_runs(
            limit=50
        )

        logger.info(
            "History list loaded (%d run(s))",
            len(runs)
        )

        return jsonify({
            "ok": True,
            "count": len(runs),
            "items": runs
        })

    except Exception:
        logger.exception(
            "Failed to load history list"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Failed to load history list"
            )
        }), 500


@history_bp.route(
    "/api/history/variables"
)
@require_api_key
def api_history_variables():
    try:
        variables = (
            get_history_variables()
        )

        logger.info(
            "History variables loaded (%d variable(s))",
            len(variables)
        )

        return jsonify({
            "ok": True,
            "variables": variables
        })

    except Exception:
        logger.exception(
            "Failed to load history variables"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Failed to load history variables"
            )
        }), 500


@history_bp.route(
    "/api/history/data"
)
@require_api_key
def api_history_data():
    try:
        tag_name = request.args.get(
            "tag_name",
            ""
        ).strip()

        if tag_name == "":
            logger.warning(
                "History data requested without tag_name"
            )

            return jsonify({
                "ok": False,
                "message": "tag_name is required",
                "points": []
            })

        points = get_history_data(
            tag_name=tag_name,
            days=2
        )

        logger.info(
            "History data loaded for '%s' (%d point(s))",
            tag_name,
            len(points)
        )

        return jsonify({
            "ok": True,
            "tag_name": tag_name,
            "points": points
        })

    except Exception:
        logger.exception(
            "Failed to load history data"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Failed to load history data"
            )
        }), 500


@history_bp.route(
    "/api/history/run/<int:run_id>"
)
@require_api_key
def api_history_run(run_id):
    try:
        detail = get_history_run_detail(
            run_id
        )

        if detail is None:
            logger.info(
                "History run %s not found",
                run_id
            )

            return jsonify({
                "ok": False,
                "message": "Run not found"
            })

        logger.info(
            "History run %s loaded",
            run_id
        )

        return jsonify({
            "ok": True,
            "run": detail["run"],
            "values": detail["values"]
        })

    except Exception:
        logger.exception(
            "Failed to load history run %s",
            run_id
        )

        return jsonify({
            "ok": False,
            "message": (
                "Failed to load history run"
            )
        }), 500