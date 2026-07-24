from flask import Blueprint, jsonify

system_bp = Blueprint(
    "system",
    __name__
)


@system_bp.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({
        "ok": True,
        "message": "API server is running"
    })