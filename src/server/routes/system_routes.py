from flask import Blueprint, jsonify

from src.logger import create_logger


logger = create_logger(
    "server.routes.system"
)


system_bp = Blueprint(
    "system",
    __name__
)


@system_bp.route(
    "/api/health",
    methods=["GET"]
)
def api_health():
    try:
        logger.info(
            "Health check requested"
        )

        return jsonify({
            "ok": True,
            "message": "API server is running"
        })

    except Exception:
        logger.exception(
            "Health check failed"
        )

        return jsonify({
            "ok": False,
            "message": "Health check failed"
        }), 500